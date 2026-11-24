"""The CLI's own logic: `--rejudge` replay, `--only-failing` selection, and recording a
run to the timestamped directory + the ledger.

Never touches a real backend or a real model -- `Judge.assess` is patched wherever a
verdict is needed, same pattern as `tests/test_judge.py`.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from conftest import make_result

import harness.cli as cli
from harness.judge import DimensionScore, JudgeVerdict
from harness.scenarios import CATALOG, INDEPENDENT_CATALOG


def _verdict(score: int = 7) -> JudgeVerdict:
    dimension = DimensionScore(score=score, reasoning="A sufficiently long dimension reason.")
    return JudgeVerdict(
        understanding=dimension,
        routing=dimension,
        policy_compliance=dimension,
        communication=dimension,
        resolution_quality=dimension,
        overall_score=score,
        reasoning="Reconstructed session, scored on the current rubric for this replay.",
        failures=[],
        strengths=[],
        verdict="PASS",
    )


def _stored_report(*entries: dict) -> dict:
    return {
        "metadata": {
            "base_url": "http://localhost:8000",
            "customer_model": "gpt-5.4-mini",
            "max_clarifications": 2,
            "rag_min_score": 0.45,
            "repeat": 1,
        },
        "results": list(entries),
    }


def _entry(name: str, *, status: str = "PASS", tags=("card_fraud",), **overrides) -> dict:
    base = {
        "scenario": name,
        "tags": list(tags),
        "status": status,
        "score": 9 if status == "PASS" else 4,
        "final_status": "ASSIGNED",
        "expected": "BLOQUEO_TARJETA · SENSIBLE · ALTO",
        "actual": "BLOQUEO_TARJETA · SENSIBLE · ALTO",
        "duration_ms": 1000,
        "session_id": "sid-1",
        "repetition": 1,
        "error": None,
        "checks": [
            {
                "name": "no_unexpected_api_errors",
                "severity": "HARD",
                "applicable": True,
                "passed": True,
                "detail": "ok",
            }
        ],
        "final_state": {"status": "ASSIGNED", "result": {"priority": "ALTO"}},
        "session_snapshot": {
            "last_category": "REPORTE_FRAUDE",
            "last_consultation_level": "SENSIBLE",
            "clarification_rounds": 0,
            "correction_rounds": 0,
            "identification_attempts": 1,
            "pii_types": [],
            "errors": [],
        },
        "transcript": [
            {
                "step": 1,
                "action": "send_turn",
                "customer": "Me robaron la tarjeta.",
                "kiosk": "¿Me confirmas que necesitas bloquear tu tarjeta?",
                "latency_ms": 500,
                "error": None,
                "decided": {"next_action": "CONFIRM", "category": "REPORTE_FRAUDE"},
            }
        ],
    }
    base.update(overrides)
    return base


# --- --only-failing ---------------------------------------------------------------------


def test_failing_scenario_names_selects_only_non_pass() -> None:
    report = _stored_report(
        _entry("a", status="PASS"), _entry("b", status="FAIL"), _entry("c", status="PARTIAL")
    )
    assert cli._failing_scenario_names(report) == ["b", "c"]


def test_failing_scenario_names_raises_when_everything_passed() -> None:
    report = _stored_report(_entry("a", status="PASS"))
    with pytest.raises(SystemExit):
        cli._failing_scenario_names(report)


# --- --rejudge ----------------------------------------------------------------------------


@pytest.fixture
def real_scenario_name() -> str:
    """A name that actually exists in the current catalog, so the reconstructed scenario
    carries a real `ExpectedOutcome` and real tags rather than being skipped as unknown."""
    return CATALOG.scenarios[0].name


async def test_rejudge_reconstructs_results_without_touching_a_client(
    tmp_path, real_scenario_name
) -> None:
    report_path = tmp_path / "source.json"
    report_path.write_text(json.dumps(_stored_report(_entry(real_scenario_name))), encoding="utf-8")
    args = cli._parse_args(["--rejudge", str(report_path), "--judge-model", "claude-haiku-5-5"])

    with patch("harness.judge.Judge.assess", AsyncMock(return_value=_verdict(8))) as assess:
        results, metadata = await cli._rejudge(args)

    assert len(results) == 1
    assert results[0].scenario == real_scenario_name
    assert results[0].verdict.overall_score == 8
    assert metadata["judge_model"] == "claude-haiku-5-5"
    assert metadata["rejudged_from"] == str(report_path)
    # the dossier the (patched) judge received was built from the *reconstructed* session
    session = assess.await_args.kwargs["session"]
    assert session.last_category == "REPORTE_FRAUDE"
    assert session.exchanges[0].customer_text == "Me robaron la tarjeta."


async def test_rejudge_skips_the_judge_for_a_scripted_scenario(tmp_path) -> None:
    protocol_name = next(s.name for s in CATALOG.scenarios if s.script is not None)
    report_path = tmp_path / "source.json"
    report_path.write_text(
        json.dumps(_stored_report(_entry(protocol_name, tags=("protocol",)))), encoding="utf-8"
    )
    args = cli._parse_args(["--rejudge", str(report_path)])

    with patch("harness.judge.Judge.assess", AsyncMock(return_value=_verdict(8))) as assess:
        results, _ = await cli._rejudge(args)

    assess.assert_not_awaited()
    assert results[0].verdict is None


async def test_rejudge_skips_scenarios_no_longer_in_the_catalog(tmp_path) -> None:
    report_path = tmp_path / "source.json"
    report_path.write_text(
        json.dumps(_stored_report(_entry("a_scenario_that_was_since_deleted"))), encoding="utf-8"
    )
    args = cli._parse_args(["--rejudge", str(report_path)])

    with patch("harness.judge.Judge.assess", AsyncMock(return_value=_verdict(8))):
        with pytest.raises(SystemExit):
            await cli._rejudge(args)


async def test_rejudge_combines_with_only_failing(tmp_path, real_scenario_name) -> None:
    other_name = CATALOG.scenarios[1].name
    report_path = tmp_path / "source.json"
    report_path.write_text(
        json.dumps(
            _stored_report(
                _entry(real_scenario_name, status="FAIL"), _entry(other_name, status="PASS")
            )
        ),
        encoding="utf-8",
    )
    args = cli._parse_args(["--rejudge", str(report_path), "--only-failing", str(report_path)])

    with patch("harness.judge.Judge.assess", AsyncMock(return_value=_verdict(8))):
        results, _ = await cli._rejudge(args)

    assert [r.scenario for r in results] == [real_scenario_name]


async def test_rejudge_finds_an_independent_scenario_without_the_catalog_flag(tmp_path) -> None:
    """A stored independent-bank report must replay as it was run, not be dropped as a
    scenario "no longer in the catalog"."""
    name = INDEPENDENT_CATALOG.scenarios[0].name
    report_path = tmp_path / "source.json"
    report = _stored_report(_entry(name, tags=("independent",)))
    report["metadata"]["catalog"] = "independent"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    args = cli._parse_args(["--rejudge", str(report_path)])

    with patch("harness.judge.Judge.assess", AsyncMock(return_value=_verdict(8))):
        results, metadata = await cli._rejudge(args)

    assert [r.scenario for r in results] == [name]
    assert metadata["catalog"] == "independent"


# --- --catalog ------------------------------------------------------------------------------


async def _selected_by(argv: list[str]) -> tuple[list[str], dict]:
    """Runs `_run` with `run_all` patched out and returns the scenario names it was handed."""
    args = cli._parse_args(argv)
    with patch.object(cli, "run_all", AsyncMock(return_value=[])) as run_all:
        _, metadata = await cli._run(args)
    return [s.name for s in run_all.await_args.kwargs["scenarios"]], metadata


async def test_the_default_run_is_still_the_full_default_catalog() -> None:
    """`make evals-live` passes no --catalog: it must keep running exactly the 48."""
    names, metadata = await _selected_by([])
    assert names == [s.name for s in CATALOG.scenarios]
    assert len(names) == 48
    assert metadata["catalog"] == "default"


async def test_catalog_independent_runs_only_the_independent_bank() -> None:
    names, metadata = await _selected_by(["--catalog", "independent"])
    assert names == [s.name for s in INDEPENDENT_CATALOG.scenarios]
    assert len(names) == 6
    assert metadata["catalog"] == "independent"


async def test_filters_apply_within_the_chosen_catalog() -> None:
    """A default-catalog name cannot leak into an independent run."""
    args = cli._parse_args(["--catalog", "independent", "--scenario", CATALOG.scenarios[0].name])
    with pytest.raises(SystemExit):
        await cli._run(args)


def test_an_unknown_catalog_is_rejected() -> None:
    with pytest.raises(SystemExit):
        cli._parse_args(["--catalog", "nope"])


def test_list_prints_the_chosen_catalog(capsys) -> None:
    cli._print_catalog("independent")
    out = capsys.readouterr().out
    assert out.startswith("6 scenarios in the independent catalog")
    assert all(s.name in out for s in INDEPENDENT_CATALOG.scenarios)
    assert CATALOG.scenarios[0].name not in out
    assert "adversarial" not in out  # tags are the chosen catalog's, not the default's


# --- recording a run ----------------------------------------------------------------------


def test_record_run_writes_only_the_run_directory_and_the_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "LEDGER_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(cli.history, "current_git_sha", lambda: "abc1234")
    monkeypatch.setattr(cli.history, "working_tree_is_dirty", lambda: False)

    results = [make_result(name="horarios_directo", score=9)]
    metadata = {
        "generated_at": "2026-08-16 14:30 UTC",
        "customer_model": "gpt-5.4-mini",
        "judge_model": "gpt-5.4-mini",
        "repeat": 1,
        "duration_seconds": 42,
    }
    cli._record_run(results, metadata)

    assert (tmp_path / "index.html").exists()
    ledger_lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger_lines) == 1
    run_id = json.loads(ledger_lines[0])["run_id"]
    assert (tmp_path / "runs" / run_id / "report.json").exists()
    assert (tmp_path / "runs" / run_id / "report.html").exists()
    assert (tmp_path / "runs" / run_id / "scorecard.md").exists()
    # No reports/latest.* alias -- reports/runs/<run_id>/ is the only copy, so nothing at
    # REPORTS_DIR's top level besides the ledger and the index should exist yet.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["history.jsonl", "index.html", "runs"]


def test_record_run_appends_rather_than_overwrites_the_ledger(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "LEDGER_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(cli.history, "current_git_sha", lambda: "abc1234")
    monkeypatch.setattr(cli.history, "working_tree_is_dirty", lambda: False)
    # Two runs recorded within the same wall-clock second must still land in two distinct
    # run directories -- run_id is stubbed per call rather than relying on real timing.
    run_ids = iter(["20260816T143000Z-abc1234", "20260816T150000Z-abc1234"])
    monkeypatch.setattr(cli.history, "make_run_id", lambda **_: next(run_ids))

    results = [make_result(name="horarios_directo", score=9)]
    metadata = {
        "generated_at": "2026-08-16 14:30 UTC",
        "customer_model": "gpt-5.4-mini",
        "judge_model": "gpt-5.4-mini",
        "repeat": 1,
        "duration_seconds": 42,
    }
    cli._record_run(results, metadata)
    cli._record_run(results, {**metadata, "generated_at": "2026-08-16 15:00 UTC"})

    ledger_lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ledger_lines) == 2
    assert len(list((tmp_path / "runs").iterdir())) == 2
