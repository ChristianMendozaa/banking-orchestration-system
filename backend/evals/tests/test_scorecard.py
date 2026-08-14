from harness.evaluator import CheckResult, EvalResult
from harness.scorecard import to_dict, to_markdown


def _results() -> list[EvalResult]:
    return [
        EvalResult(
            persona="persona_a",
            final_status="RESOLVED_AUTOMATIC",
            checks=[CheckResult("check_1", True, "ok"), CheckResult("check_2", True, "ok")],
        ),
        EvalResult(
            persona="persona_b",
            final_status="ASSIGNED",
            checks=[CheckResult("check_1", True, "ok"), CheckResult("check_2", False, "fallo")],
        ),
    ]


def test_to_dict_aggregates_pass_counts() -> None:
    summary = to_dict(_results())
    assert summary["personas_total"] == 2
    assert summary["personas_passed"] == 1
    assert summary["checks_total"] == 4
    assert summary["checks_passed"] == 3


def test_to_dict_preserves_per_persona_detail() -> None:
    summary = to_dict(_results())
    persona_b = next(row for row in summary["results"] if row["persona"] == "persona_b")
    assert persona_b["passed"] is False
    assert persona_b["checks"][1] == {"name": "check_2", "passed": False, "detail": "fallo"}


def test_to_markdown_marks_failed_persona() -> None:
    markdown = to_markdown(_results())
    assert "✅ persona_a" in markdown
    assert "❌ persona_b" in markdown
    assert "1/2 aprobadas" in markdown


def test_empty_results_render_without_error() -> None:
    summary = to_dict([])
    assert summary["personas_total"] == 0
    assert "0/0" in to_markdown([])
