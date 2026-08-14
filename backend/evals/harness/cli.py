"""CLI entrypoint: `python -m harness [options]`.

Requires a live backend and, unless `--no-judge` is passed, `OPENAI_API_KEY` for both the
simulated customer and the judge -- real, billed API calls on both sides plus the
backend's own classification, embedding and retrieval calls.

Exits non-zero if any scenario did not pass, so it still works as a manually triggered CI
gate.
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

from harness.report import html, json_report, markdown
from harness.runner import run_all
from harness.scenarios import CATALOG, all_tags
from harness.scoring import ScenarioResult, summarize

logger = structlog.get_logger()

DEFAULT_CUSTOMER_MODEL = "gpt-5.4-mini"
DEFAULT_JUDGE_MODEL = "gpt-5.4"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


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
        help="Model that scores each session. Use a strong one: it grades the system.",
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
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run the whole selection N times to observe score variance.",
    )
    parser.add_argument("--output", default=None, help="Path for the markdown scorecard.")
    parser.add_argument("--json-output", default=None, help="Path for the JSON report.")
    parser.add_argument(
        "--html",
        nargs="?",
        const="",
        default=None,
        help="Path for the HTML dashboard. Bare flag writes reports/latest.html.",
    )
    parser.add_argument("--list", action="store_true", help="List the catalog and exit.")
    return parser.parse_args(argv)


def _write(path: Path, content: str) -> None:
    """Every output path creates its own directory. `reports/` is gitignored, so on a
    fresh clone it does not exist and the default paths would otherwise fail."""
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


async def _run(args: argparse.Namespace) -> list[ScenarioResult]:
    selected = CATALOG.filter(names=args.scenario, tags=args.tag)
    if not selected:
        raise SystemExit("No scenario matched the given --scenario/--tag filters.")

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

    scorecard = markdown.to_markdown(results, duration_seconds=duration)
    print(scorecard)
    if args.output:
        _write(Path(args.output), scorecard)
    if args.json_output:
        payload = json_report.to_dict(results, metadata=metadata)
        _write(Path(args.json_output), json.dumps(payload, ensure_ascii=False, indent=2))
    html_path = _resolve_html_path(args.html)
    if html_path:
        _write(html_path, html.to_html(results, metadata=metadata))
        print(f"\nDashboard: {html_path.resolve().as_uri()}")

    summary = summarize(results, duration_seconds=duration)
    print(
        f"\nScenarios: {summary.passed}/{summary.total} passed · "
        f"average score {summary.average_score:.1f}/10 · "
        f"checks {summary.checks_passed}/{summary.checks_total} · "
        f"{duration // 60}m {duration % 60:02d}s"
    )
    return results


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if args.list:
        _print_catalog()
        return
    results = asyncio.run(_run(args))
    sys.exit(0 if all(result.passed for result in results) else 1)


if __name__ == "__main__":
    main()
