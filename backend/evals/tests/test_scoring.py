"""The rule that keeps the judge honest: policy outranks opinion."""

from conftest import make_result, make_verdict

from harness.evaluator import CheckResult
from harness.scoring import (
    HARD_FAILURE_SCORE_CAP,
    PASS_THRESHOLD,
    group_averages,
    summarize,
)

HARD_FAIL = CheckResult("fraud_reaches_critical", False, "priority=ALTO")
SOFT_FAIL = CheckResult("routed_to_skilled_executive", False, "sin skill", severity="SOFT")
SKIPPED = CheckResult.skip("automatic_answers_are_cited", "no fue automatico")
PASSING = CheckResult("clarifications_bounded", True, "rounds=0")


def test_a_hard_failure_caps_a_glowing_judge_score() -> None:
    result = make_result(score=10, checks=[HARD_FAIL])
    assert result.raw_score == 10
    assert result.score == HARD_FAILURE_SCORE_CAP
    assert result.status == "FAIL"
    assert result.was_capped is True


def test_the_cap_never_raises_a_low_score() -> None:
    result = make_result(score=2, checks=[HARD_FAIL])
    assert result.score == 2
    assert result.was_capped is False


def test_a_soft_failure_does_not_cap() -> None:
    result = make_result(score=9, checks=[SOFT_FAIL])
    assert result.score == 9
    assert result.status == "PASS"


def test_a_skipped_check_does_not_cap() -> None:
    result = make_result(score=9, checks=[SKIPPED])
    assert result.score == 9
    assert result.status == "PASS"


def test_a_clean_run_below_the_threshold_is_partial_not_failed() -> None:
    result = make_result(score=PASS_THRESHOLD - 1, checks=[PASSING])
    assert result.status == "PARTIAL"
    assert result.passed is False


def test_a_crashed_scenario_fails_regardless_of_score() -> None:
    result = make_result(score=9, checks=[PASSING], error="TimeoutError: boom")
    assert result.status == "FAIL"
    assert "did not complete" in result.reasoning


def test_reasoning_explains_the_cap_and_keeps_the_judges_words() -> None:
    result = make_result(score=10, checks=[HARD_FAIL])
    reasoning = result.reasoning
    assert "capped at 4/10" in reasoning
    assert "fraud_reaches_critical" in reasoning
    assert make_verdict(10).reasoning in reasoning


def test_the_cap_reason_names_every_failed_hard_check() -> None:
    result = make_result(
        score=10,
        checks=[HARD_FAIL, CheckResult("expected_category", False, "actual=CONSULTA_GENERAL")],
    )
    assert result.score_cap_reason == "fraud_reaches_critical, expected_category"


def test_there_is_no_cap_reason_when_nothing_was_capped() -> None:
    assert make_result(score=9, checks=[PASSING]).score_cap_reason is None


def test_with_no_judge_a_clean_scenario_still_passes_on_its_checks() -> None:
    """`--no-judge` disables the judge; it does not fail every scenario."""
    result = make_result(checks=[PASSING, SKIPPED], verdict=None)
    assert result.score == 10
    assert result.status == "PASS"
    assert "1 of 1 applicable checks passed" in result.reasoning


def test_with_no_judge_a_soft_failure_lowers_the_score() -> None:
    result = make_result(checks=[PASSING, SOFT_FAIL], verdict=None)
    assert result.score == 7
    assert "routed_to_skilled_executive" in result.reasoning


def test_with_no_judge_a_hard_failure_still_fails() -> None:
    result = make_result(checks=[HARD_FAIL], verdict=None)
    assert result.score == HARD_FAILURE_SCORE_CAP
    assert result.status == "FAIL"


def test_a_judge_that_ran_and_failed_scores_one_rather_than_passing_by_default() -> None:
    """The distinction that matters: a disabled judge falls back to the checks; a broken
    one must not look like a clean run."""
    from harness.judge import JudgeVerdict

    result = make_result(checks=[PASSING], verdict=JudgeVerdict.unavailable("RateLimitError"))
    assert result.score == 1
    assert result.status == "FAIL"


def test_summary_counts_only_applicable_checks() -> None:
    summary = summarize([make_result(checks=[PASSING, SKIPPED, SOFT_FAIL])])
    assert summary.checks_total == 2
    assert summary.checks_passed == 1


def test_summary_aggregates_scores_and_pass_rate() -> None:
    summary = summarize(
        [
            make_result(name="a", score=10, checks=[PASSING]),
            make_result(name="b", score=10, checks=[HARD_FAIL]),
        ]
    )
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.pass_rate == 50.0
    assert summary.average_score == 7.0  # 10 and a capped 4
    assert summary.hard_failures == 1


def test_group_averages_bucket_by_group() -> None:
    averages = group_averages(
        [
            make_result(name="a", group="card_fraud", score=6),
            make_result(name="b", group="card_fraud", score=8),
            make_result(name="c", group="adversarial", score=3),
        ]
    )
    assert averages == {"card_fraud": 7.0, "adversarial": 3.0}


def test_empty_run_summarizes_without_dividing_by_zero() -> None:
    summary = summarize([])
    assert summary.total == 0
    assert summary.average_score == 0.0
    assert summary.check_pass_rate == 0.0
