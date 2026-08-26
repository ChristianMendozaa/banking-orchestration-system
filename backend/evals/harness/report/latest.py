"""Read the newest saved live-evaluation report without running an evaluation.

This module intentionally uses only the standard library.  It is called by ``make check``
to surface existing evidence, never to start Docker, contact a model, or require a key.
"""

import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def latest_report_path(reports_dir: Path = REPORTS_DIR) -> Path | None:
    """Return the timestamp-sorted newest complete JSON report, if one exists."""
    runs_dir = reports_dir / "runs"
    reports = sorted(path for path in runs_dir.glob("*/report.json") if path.is_file())
    return reports[-1] if reports else None


def _duration(seconds: object) -> str:
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return "unknown"
    return f"{value // 60}m {value % 60:02d}s"


def _value(mapping: dict[str, Any], key: str, fallback: str = "unknown") -> object:
    value = mapping.get(key)
    return fallback if value is None else value


def render_latest_report(reports_dir: Path = REPORTS_DIR) -> str:
    """Render saved-run metrics as informational evidence and never raise for missing data."""
    path = latest_report_path(reports_dir)
    heading = "\n\033[1mLAST LIVE EVALUATION (informational; not re-run)\033[0m"
    if path is None:
        return (
            f"{heading}\n"
            "  No saved report is available. Run make evals-live deliberately to create one."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata = payload["metadata"]
        summary = payload["summary"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        return f"{heading}\n  Latest saved report is unreadable: {error}\n  Source: {path}"

    run_id = path.parent.name
    passed = _value(summary, "scenarios_passed")
    total = _value(summary, "scenarios_total")
    partial = _value(summary, "scenarios_partial")
    failed = _value(summary, "scenarios_failed")
    checks_passed = _value(summary, "checks_passed")
    checks_total = _value(summary, "checks_total")
    return "\n".join(
        (
            heading,
            f"  Run: {run_id} · recorded {_value(metadata, 'generated_at')}",
            f"  Revision: {_value(metadata, 'git_sha')} · dirty={_value(metadata, 'git_dirty')}",
            "  Models: "
            f"customer={_value(metadata, 'customer_model')} "
            f"· judge={_value(metadata, 'judge_model')}",
            f"  Scenarios: {passed}/{total} passed · {partial} partial · {failed} failed "
            f"· pass rate {_value(summary, 'pass_rate')}%",
            f"  Score: {_value(summary, 'average_score')}/10 "
            f"· checks {checks_passed}/{checks_total} "
            f"· hard failures {_value(summary, 'hard_failures')}",
            f"  Duration: {_duration(metadata.get('duration_seconds'))}",
            f"  Source: {path}",
        )
    )


def main() -> None:
    print(render_latest_report())


if __name__ == "__main__":
    main()
