import json

from harness.report.latest import latest_report_path, render_latest_report


def _report(*, run_id: str, passed: int = 42) -> dict:
    return {
        "metadata": {
            "generated_at": "2026-08-25 21:08 UTC",
            "git_sha": "21fe4bf",
            "git_dirty": False,
            "customer_model": "gpt-5.4-mini",
            "judge_model": "gpt-5.4-mini",
            "duration_seconds": 538,
        },
        "summary": {
            "scenarios_total": 45,
            "scenarios_passed": passed,
            "scenarios_partial": 1,
            "scenarios_failed": 2,
            "average_score": 9.27,
            "pass_rate": 93.3,
            "checks_total": 446,
            "checks_passed": 440,
            "hard_failures": 1,
        },
    }


def _write_report(reports_dir, run_id: str) -> None:
    path = reports_dir / "runs" / run_id / "report.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_report(run_id=run_id)), encoding="utf-8")


def test_latest_report_uses_the_newest_timestamped_run(tmp_path) -> None:
    _write_report(tmp_path, "20260825T210844Z-21fe4bf")
    _write_report(tmp_path, "20260826T100000Z-nextsha")

    latest = latest_report_path(tmp_path)

    assert latest is not None
    assert latest.parent.name == "20260826T100000Z-nextsha"
    rendered = render_latest_report(tmp_path)
    assert "42/45 passed" in rendered
    assert "9.27/10" in rendered
    assert "8m 58s" in rendered
    assert "informational; not re-run" in rendered


def test_latest_report_is_informational_when_no_saved_run_exists(tmp_path) -> None:
    assert latest_report_path(tmp_path) is None
    assert "No saved report is available" in render_latest_report(tmp_path)


def test_latest_report_does_not_raise_for_malformed_newest_report(tmp_path) -> None:
    valid = tmp_path / "runs" / "20260825T210844Z-valid" / "report.json"
    valid.parent.mkdir(parents=True)
    valid.write_text(json.dumps(_report(run_id="valid")), encoding="utf-8")
    broken = tmp_path / "runs" / "20260826T100000Z-broken" / "report.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("not-json", encoding="utf-8")

    rendered = render_latest_report(tmp_path)

    assert "Latest saved report is unreadable" in rendered
    assert "20260826T100000Z-broken" in rendered
