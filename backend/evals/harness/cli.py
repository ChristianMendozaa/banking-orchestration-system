"""CLI entrypoint: `python -m harness [options]`.

Requires a live backend and, unless `--no-judge` is passed, `OPENAI_API_KEY` for both the
simulated customer and the judge -- real, billed API calls on both sides plus the
backend's own classification, embedding and retrieval.

Exits non-zero if any scenario did not pass, so it still works as a manually triggered CI
gate.

Every run that produces results (a live run or a `--rejudge` replay) is recorded forever:
it gets its own `reports/runs/<run_id>/` directory, `reports/latest.*` is refreshed to
point at it, and a summary line is appended to the git-tracked `reports/history.jsonl`
ledger. `reports/index.html`, the cross-run trend dashboard, is rebuilt from that ledger
after every run and on demand with `--rebuild-index`.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import structlog

from harness.client import SessionHandle
from harness.evaluator import CheckResult
from harness.judge import Judge
from harness.model_client import resolve_provider
from harness.report import history, html, json_report, markdown
from harness.runner import JUDGE_TIMEOUT_SECONDS, run_all
from harness.scenarios import CATALOG, all_tags
from harness.scoring import ScenarioResult, summarize
from harness.session import ConversationSession, ExchangeRecord

logger = structlog.get_logger()

DEFAULT_CUSTOMER_MODEL = "gpt-5.4-mini"
# Mini, not flagship: a `reasoning_effort="high"` mini judge (see `judge.py`) keeps
# roughly flagship-level discrimination at a fraction of the price, and `--judge-model
# gpt-5.4` remains available for a deliberate milestone run. See `backend/evals/README.md`
# for the calibration numbers behind this default.
DEFAULT_JUDGE_MODEL = "gpt-5.4-mini"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
LEDGER_PATH = REPORTS_DIR / history.LEDGER_FILENAME


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the kiosk orchestration policy end to end against a live backend."
    )
    parser.add_argument(
        "--base-url", default=os.environ.get("EVAL_API_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("EVAL_MODEL", DEFAULT_CUSTOMER_MODEL),
        help="Model that plays the simulated customer.",
    )
    parser.add_argument(
        "--judge-model",
        default=os.environ.get("EVAL_JUDGE_MODEL", DEFAULT_JUDGE_MODEL),
        help="Model that scores each session. Also used to re-score with --rejudge.",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip the LLM judge and report deterministic checks only (no judge cost).",
    )
    parser.add_argument(
        "--max-clarifications",
        type=int,
        default=int(os.environ.get("EVAL_MAX_CLARIFICATIONS", "2")),
        help="Must match the evaluated backend's MAX_CLARIFICATIONS setting.",
    )
    parser.add_argument(
        "--rag-min-score",
        type=float,
        default=float(os.environ.get("EVAL_RAG_MIN_SCORE", "0.45")),
        help="Must match the evaluated backend's RAG_MIN_SCORE setting.",
    )
    parser.add_argument(
        "--scenario", action="append", default=None, help="Run only these scenarios (repeatable)."
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=None,
        help=f"Run only scenarios with these tags (repeatable). Available: {', '.join(all_tags())}",
    )
    parser.add_argument(
        "--only-failing",
        default=None,
        metavar="REPORT.json",
        help=(
            "Run (or --rejudge) only the scenarios that were not PASS in a prior JSON "
            "report. Combines with --scenario/--tag rather than replacing them."
        ),
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run the whole selection N times to observe score variance.",
    )
    parser.add_argument("--output", default=None, help="Extra path for the markdown scorecard.")
    parser.add_argument("--json-output", default=None, help="Extra path for the JSON report.")
    parser.add_argument(
        "--html",
        nargs="?",
        const="",
        default=None,
        help="Extra path for the HTML dashboard (reports/latest.html is always written).",
    )
    parser.add_argument(
        "--rejudge",
        default=None,
        metavar="REPORT.json",
        help=(
            "Re-score a stored JSON report's sessions with the current judge -- no "
            "backend, no docker, no customer simulator, no new billed customer calls. "
            "Useful for calibrating a judge-model or prompt change against a run already "
            "paid for."
        ),
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild reports/index.html from reports/history.jsonl and exit. Runs nothing.",
    )
    parser.add_argument("--list", action="store_true", help="List the catalog and exit.")
    return parser.parse_args(argv)


def _write(path: Path, content: str) -> None:
    """Every output path creates its own directory. `reports/` is gitignored (besides the
    ledger), so on a fresh clone it does not exist and the default paths would otherwise
    fail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _resolve_html_path(value: str | None) -> Path | None:
    if value is None:
        return None
    return Path(value) if value else REPORTS_DIR / "latest.html"


def _print_catalog() -> None:
    print(f"{len(CATALOG.scenarios)} scenarios\n")
    for scenario in CATALOG.scenarios:
        print(f"  {scenario.name:<38} {','.join(scenario.tags)}")
    print(f"\ntags: {', '.join(all_tags())}")


def _load_report(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _failing_scenario_names(report: dict) -> list[str]:
    names = sorted({entry["scenario"] for entry in report["results"] if entry["status"] != "PASS"})
    if not names:
        raise SystemExit("No non-PASS scenarios found in that report.")
    return names


async def _run(args: argparse.Namespace) -> tuple[list[ScenarioResult], dict]:
    provider, _ = resolve_provider(args.model)
    if provider is not None:
        # The simulated customer needs AutoGen tool-calling for its three bound tools
        # (send_turn/send_confirmation/send_identification) -- neither local CLI exposes
        # arbitrary user-defined function calling the way the Chat Completions API does,
        # so only --judge-model may point at one. Caught here, at argument-parsing time,
        # rather than letting it fail deep inside AutoGen with a confusing error.
        raise SystemExit(
            f"--model {args.model!r} is judge-only: the simulated customer needs OpenAI "
            "tool-calling, which claude-code/codex CLIs don't expose. Use --judge-model "
            f"{args.model!r} instead, and pick an OpenAI model for --model."
        )
    names = list(args.scenario) if args.scenario else None
    if args.only_failing:
        failing = _failing_scenario_names(_load_report(args.only_failing))
        names = sorted(set(names or []) | set(failing)) if names else failing

    selected = CATALOG.filter(names=names, tags=args.tag)
    if not selected:
        raise SystemExit("No scenario matched the given --scenario/--tag/--only-failing filters.")

    judge_model = None if args.no_judge else args.judge_model
    logger.info(
        "run_started",
        scenarios=len(selected),
        repeat=args.repeat,
        customer_model=args.model,
        judge_model=judge_model or "disabled",
        base_url=args.base_url,
    )
    started = time.monotonic()
    results = await run_all(
        base_url=args.base_url,
        model=args.model,
        judge_model=judge_model,
        max_clarifications=args.max_clarifications,
        rag_min_score=args.rag_min_score,
        scenarios=selected,
        concurrency=args.concurrency,
        repeat=args.repeat,
    )
    duration = int(time.monotonic() - started)

    metadata = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "base_url": args.base_url,
        "customer_model": args.model,
        "judge_model": judge_model,
        "max_clarifications": args.max_clarifications,
        "rag_min_score": args.rag_min_score,
        "repeat": args.repeat,
        "duration_seconds": duration,
    }
    return results, metadata


async def _rejudge(args: argparse.Namespace) -> tuple[list[ScenarioResult], dict]:
    """Rebuilds each stored session's dossier from `session_snapshot` + `transcript` +
    `final_state` (see `harness/report/json_report.py`) and re-runs only the judge --
    the customer simulator and the backend under test are never touched."""
    source = _load_report(args.rejudge)
    entries = source["results"]

    names = set(args.scenario) if args.scenario else None
    if args.only_failing:
        failing = set(_failing_scenario_names(_load_report(args.only_failing)))
        names = (names | failing) if names else failing
    if names is not None:
        entries = [entry for entry in entries if entry["scenario"] in names]
    if args.tag:
        wanted_tags = set(args.tag)
        entries = [entry for entry in entries if wanted_tags & set(entry.get("tags") or [])]
    if not entries:
        raise SystemExit("No scenarios in the stored report matched the given filters.")

    catalog_by_name = {scenario.name: scenario for scenario in CATALOG.scenarios}
    logger.info(
        "rejudge_started", scenarios=len(entries), judge_model=args.judge_model, source=args.rejudge
    )
    started = time.monotonic()
    judge = Judge(args.judge_model)
    results: list[ScenarioResult] = []
    try:
        for entry in entries:
            scenario = catalog_by_name.get(entry["scenario"])
            if scenario is None:
                logger.warning(
                    "rejudge_skipped_unknown_scenario",
                    scenario=entry["scenario"],
                    reason="not in the current catalog -- renamed or removed since that run",
                )
                continue
            checks = [
                CheckResult(c["name"], c["passed"], c["detail"], c["severity"], c["applicable"])
                for c in entry.get("checks", [])
            ]
            snapshot = entry.get("session_snapshot") or {}
            session = ConversationSession(
                None, SessionHandle(entry.get("session_id") or "replay", "replay")
            )
            session.last_category = snapshot.get("last_category")
            session.last_consultation_level = snapshot.get("last_consultation_level")
            session.clarification_rounds = snapshot.get("clarification_rounds", 0)
            session.correction_rounds = snapshot.get("correction_rounds", 0)
            session.identification_attempts = snapshot.get("identification_attempts", 0)
            session.pii_types = snapshot.get("pii_types") or []
            session.errors = snapshot.get("errors") or []
            session.exchanges = [
                ExchangeRecord(
                    index=step["step"] - 1,
                    tool=step["action"],
                    customer_text=step.get("customer"),
                    kiosk_speech=step.get("kiosk"),
                    response=step.get("decided") or {},
                    latency_ms=step.get("latency_ms", 0),
                    error=step.get("error"),
                )
                for step in entry.get("transcript", [])
            ]
            final_state = entry.get("final_state") or {}
            result = ScenarioResult(
                scenario=scenario.name,
                group=scenario.group,
                tags=list(scenario.tags),
                description=scenario.description,
                final_status=entry.get("final_status", "UNKNOWN"),
                checks=checks,
                expected_summary=entry.get("expected", ""),
                actual_summary=entry.get("actual", ""),
                duration_ms=entry.get("duration_ms", 0),
                session_id=entry.get("session_id"),
                repetition=entry.get("repetition", 1),
                error=entry.get("error"),
                exchanges=session.exchanges,
                final_state=final_state,
                session_snapshot=snapshot,
            )
            # Same rule as a live run: a scripted protocol scenario has nothing for the
            # judge to assess, so its score stays purely deterministic.
            if scenario.script is None:
                result.verdict = await asyncio.wait_for(
                    judge.assess(
                        scenario=scenario, session=session, final_state=final_state, checks=checks
                    ),
                    JUDGE_TIMEOUT_SECONDS,
                )
            results.append(result)
    finally:
        await judge.close()
    if not results:
        raise SystemExit(
            "None of the scenarios in that report exist in the current catalog "
            "(renamed or removed since that run)."
        )
    duration = int(time.monotonic() - started)

    order = {scenario.name: index for index, scenario in enumerate(CATALOG.scenarios)}
    results.sort(key=lambda item: (order.get(item.scenario, 0), item.repetition))

    source_metadata = source.get("metadata") or {}
    metadata = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "base_url": source_metadata.get("base_url", "n/a (rejudge -- backend not called)"),
        "customer_model": source_metadata.get("customer_model", "n/a (rejudge)"),
        "judge_model": args.judge_model,
        "max_clarifications": source_metadata.get("max_clarifications"),
        "rag_min_score": source_metadata.get("rag_min_score"),
        "repeat": source_metadata.get("repeat", 1),
        "duration_seconds": duration,
        "rejudged_from": args.rejudge,
    }
    return results, metadata


def _run_hrefs(runs: list[dict]) -> dict[str, str]:
    hrefs = {}
    for run in runs:
        if (REPORTS_DIR / "runs" / run["run_id"] / "report.html").exists():
            hrefs[run["run_id"]] = f"runs/{run['run_id']}/report.html"
    return hrefs


def _record_run(results: list[ScenarioResult], metadata: dict) -> None:
    """Writes the timestamped run directory, refreshes `latest.*`, appends the ledger and
    rebuilds the trend dashboard -- every run, unconditionally, regardless of what
    `--output`/`--json-output`/`--html` were passed. Those flags add an *extra* copy
    somewhere else; they no longer gate whether history is kept at all."""
    git_sha = history.current_git_sha()
    git_dirty = history.working_tree_is_dirty()
    metadata = {**metadata, "git_sha": git_sha, "git_dirty": git_dirty}
    run_id = history.make_run_id(git_sha=git_sha)

    scorecard = markdown.to_markdown(results, duration_seconds=metadata.get("duration_seconds", 0))
    json_payload = json.dumps(
        json_report.to_dict(results, metadata=metadata), ensure_ascii=False, indent=2
    )
    html_page = html.to_html(results, metadata=metadata)

    run_dir = REPORTS_DIR / "runs" / run_id
    _write(run_dir / "scorecard.md", scorecard)
    _write(run_dir / "report.json", json_payload)
    _write(run_dir / "report.html", html_page)
    _write(REPORTS_DIR / "latest.md", scorecard)
    _write(REPORTS_DIR / "latest.json", json_payload)
    _write(REPORTS_DIR / "latest.html", html_page)

    record = history.build_run_record(
        results, run_id=run_id, metadata=metadata, git_sha=git_sha, git_dirty=git_dirty
    )
    history.append_run(LEDGER_PATH, record)
    runs = history.load_runs(LEDGER_PATH)
    _write(REPORTS_DIR / "index.html", history.to_html(runs, run_hrefs=_run_hrefs(runs)))

    print(f"\nRun recorded: {run_id}")
    print(f"Dashboard: {(run_dir / 'report.html').resolve().as_uri()}")
    print(f"History:   {(REPORTS_DIR / 'index.html').resolve().as_uri()}")


def _finish(results: list[ScenarioResult], metadata: dict, args: argparse.Namespace) -> None:
    scorecard = markdown.to_markdown(results, duration_seconds=metadata.get("duration_seconds", 0))
    print(scorecard)
    if args.output:
        _write(Path(args.output), scorecard)
    if args.json_output:
        payload = json_report.to_dict(results, metadata=metadata)
        _write(Path(args.json_output), json.dumps(payload, ensure_ascii=False, indent=2))
    html_path = _resolve_html_path(args.html)
    if html_path:
        _write(html_path, html.to_html(results, metadata=metadata))

    _record_run(results, metadata)

    duration = metadata.get("duration_seconds", 0)
    summary = summarize(results, duration_seconds=duration)
    print(
        f"\nScenarios: {summary.passed}/{summary.total} passed · "
        f"average score {summary.average_score:.1f}/10 · "
        f"checks {summary.checks_passed}/{summary.checks_total} · "
        f"{duration // 60}m {duration % 60:02d}s"
    )


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if args.list:
        _print_catalog()
        return
    if args.rebuild_index:
        runs = history.load_runs(LEDGER_PATH)
        path = REPORTS_DIR / "index.html"
        _write(path, history.to_html(runs, run_hrefs=_run_hrefs(runs)))
        print(f"Rebuilt {path.resolve().as_uri()} from {len(runs)} run(s) in {LEDGER_PATH}")
        return

    if args.rejudge:
        results, metadata = asyncio.run(_rejudge(args))
    else:
        results, metadata = asyncio.run(_run(args))
    _finish(results, metadata, args)
    sys.exit(0 if all(result.passed for result in results) else 1)


if __name__ == "__main__":
    main()
