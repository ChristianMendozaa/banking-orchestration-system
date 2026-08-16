"""The append-only run ledger and the cross-run trend dashboard rendered from it.

`build_run_record`/`append_run`/`load_runs` are what let `reports/history.jsonl` be a
git-tracked, ever-growing record of runs; `to_html` is what turns that record into
something a human can actually read. Neither touches the network or a real model.
"""

import json

from conftest import make_result

from harness.evaluator import CheckResult
from harness.report import history

METADATA = {
    "generated_at": "2026-08-16 14:30 UTC",
    "customer_model": "gpt-5.4-mini",
    "judge_model": "gpt-5.4-mini",
    "repeat": 1,
    "duration_seconds": 120,
}


def _results() -> list:
    return [
        make_result(name="horarios_directo", group="general_inquiry", score=9),
        make_result(name="tarjeta_robada_angustiado", group="card_fraud", score=4),
    ]


# --- the ledger -----------------------------------------------------------------------


def test_build_run_record_matches_the_scoring_summary() -> None:
    record = history.build_run_record(
        _results(), run_id="run-1", metadata=METADATA, git_sha="abc1234", git_dirty=False
    )
    assert record["run_id"] == "run-1"
    assert record["git_sha"] == "abc1234"
    assert record["judge_model"] == "gpt-5.4-mini"
    assert record["summary"]["scenarios_passed"] == 1
    assert record["scenarios"]["horarios_directo"] == {"status": "PASS", "score": 9}
    assert record["scenarios"]["tarjeta_robada_angustiado"]["status"] in {"FAIL", "PARTIAL"}


def test_build_run_record_counts_only_judged_scenarios() -> None:
    judged = make_result(name="a")
    unjudged = make_result(name="b", verdict=None)
    record = history.build_run_record(
        [judged, unjudged], run_id="run-1", metadata=METADATA, git_sha="abc", git_dirty=False
    )
    assert record["judged_scenarios"] == 1
    assert record["scenarios_total"] == 2


def test_append_and_load_round_trip(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    record = history.build_run_record(
        _results(), run_id="run-1", metadata=METADATA, git_sha="abc", git_dirty=False
    )
    history.append_run(path, record)
    history.append_run(
        path,
        history.build_run_record(
            _results(), run_id="run-2", metadata=METADATA, git_sha="def", git_dirty=True
        ),
    )
    runs = history.load_runs(path)
    assert [run["run_id"] for run in runs] == ["run-1", "run-2"]


def test_load_runs_on_a_missing_ledger_is_an_empty_list(tmp_path) -> None:
    assert history.load_runs(tmp_path / "does-not-exist.jsonl") == []


def test_append_run_creates_the_reports_directory(tmp_path) -> None:
    path = tmp_path / "nested" / "reports" / "history.jsonl"
    history.append_run(
        path,
        history.build_run_record(
            _results(), run_id="run-1", metadata=METADATA, git_sha="abc", git_dirty=False
        ),
    )
    assert path.exists()


def test_ledger_lines_are_one_json_object_each(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    history.append_run(
        path,
        history.build_run_record(
            _results(), run_id="run-1", metadata=METADATA, git_sha="abc", git_dirty=False
        ),
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    json.loads(lines[0])  # does not raise


# --- the trend dashboard ----------------------------------------------------------------


def _runs(*, judge_models: list[str] | None = None) -> list[dict]:
    runs = []
    for index in range(3):
        record = history.build_run_record(
            _results(),
            run_id=f"run-{index}",
            metadata={**METADATA, "generated_at": f"2026-08-1{index} 00:00 UTC"},
            git_sha=f"sha{index}",
            git_dirty=False,
        )
        if judge_models:
            record["judge_model"] = judge_models[index]
        runs.append(record)
    return runs


def test_history_dashboard_is_self_contained() -> None:
    import re

    page = history.to_html(_runs())
    for pattern in (r'src\s*=\s*["\']https?://', r"\bfetch\s*\(", r"new\s+WebSocket"):
        assert not re.search(pattern, page)


def test_history_dashboard_renders_with_no_runs() -> None:
    page = history.to_html([])
    assert "0 runs recorded" in page


def test_history_dashboard_shows_run_count_and_latest_numbers() -> None:
    page = history.to_html(_runs())
    assert "3 runs recorded" in page
    assert "Latest pass rate" in page


def test_history_dashboard_marks_a_judge_model_change() -> None:
    page = history.to_html(_runs(judge_models=["gpt-5.4", "gpt-5.4", "gpt-5.4-mini"]))
    assert "milestone" in page


def test_history_dashboard_links_to_each_runs_own_report() -> None:
    runs = _runs()
    hrefs = {run["run_id"]: f"runs/{run['run_id']}/report.html" for run in runs}
    page = history.to_html(runs, run_hrefs=hrefs)
    assert "runs/run-0/report.html" in page


def test_history_dashboard_matrix_shows_a_scenario_that_regressed() -> None:
    """The matrix is what a pass-rate line alone cannot show: this scenario passed, then
    regressed to a hard failure -- that is a finding a single trend number would hide if
    something else improved at the same time."""
    passing = make_result(name="horarios_directo", score=9)
    regressed = make_result(
        name="horarios_directo",
        score=4,
        checks=[CheckResult("expected_priority", False, "actual=BAJO esperado=ALTO")],
    )
    run1 = history.build_run_record(
        [passing], run_id="run-a", metadata=METADATA, git_sha="a", git_dirty=False
    )
    run2 = history.build_run_record(
        [regressed], run_id="run-b", metadata=METADATA, git_sha="b", git_dirty=False
    )
    page = history.to_html([run1, run2])
    assert "swatch pass" in page
    assert "swatch fail" in page


def test_history_dashboard_marks_a_scenario_missing_from_an_earlier_run() -> None:
    """A scenario added after run 1 must render as 'not run', not silently disappear from
    a row that other runs populate."""
    only_in_run2 = make_result(name="new_scenario", score=8)
    run1 = history.build_run_record(
        [make_result(name="old_scenario", score=8)],
        run_id="run-a",
        metadata=METADATA,
        git_sha="a",
        git_dirty=False,
    )
    run2 = history.build_run_record(
        [only_in_run2], run_id="run-b", metadata=METADATA, git_sha="b", git_dirty=False
    )
    page = history.to_html([run1, run2])
    assert "swatch missing" in page
