"""Combines the deterministic checks and the judge's opinion into one score.

The rule that matters is the cap: **a HARD policy failure caps the final score at 4/10,
whatever the judge thought.** A session can be warm, fluent and reassuring and still have
failed to take a fraud report to `CRITICO`, and a scoring scheme that lets charm outrank
policy would be worse than no scoring at all. The judge's own reasoning is kept verbatim
alongside the cap, so the report shows both what the model thought and why the number was
overruled.

Nothing here calls a model. `ScenarioResult` is the single object every report renderer
consumes.
"""

import math
from dataclasses import dataclass, field
from typing import Literal

from harness.evaluator import CheckResult
from harness.judge import JudgeVerdict
from harness.session import ExchangeRecord

HARD_FAILURE_SCORE_CAP = 4
PASS_THRESHOLD = 7
PARTIAL_THRESHOLD = 4


@dataclass(slots=True)
class ScenarioResult:
    scenario: str
    group: str
    tags: list[str]
    description: str
    final_status: str
    checks: list[CheckResult] = field(default_factory=list)
    verdict: JudgeVerdict | None = None
    exchanges: list[ExchangeRecord] = field(default_factory=list)
    expected_summary: str = ""
    actual_summary: str = ""
    duration_ms: int = 0
    session_id: str | None = None
    repetition: int = 1
    error: str | None = None
    # The system's final `GET /kiosk/sessions/{id}` body, and the handful of scalars the
    # judge's dossier reads off `ConversationSession` (category, consultation level,
    # clarification/correction/identification counts, PII types, API errors). Carried on
    # the result -- not just summarised into `actual_summary` -- so a stored JSON report
    # has everything `--rejudge` needs to rebuild the dossier without a second live run.
    final_state: dict = field(default_factory=dict)
    session_snapshot: dict = field(default_factory=dict)

    @property
    def hard_failures(self) -> list[CheckResult]:
        return [check for check in self.checks if check.failed_hard]

    @property
    def soft_failures(self) -> list[CheckResult]:
        return [
            check
            for check in self.checks
            if check.applicable and not check.passed and check.severity == "SOFT"
        ]

    @property
    def applicable_checks(self) -> list[CheckResult]:
        return [check for check in self.checks if check.applicable]

    @property
    def score(self) -> int:
        return min(self.raw_score, HARD_FAILURE_SCORE_CAP) if self.hard_failures else self.raw_score

    @property
    def raw_score(self) -> int:
        return self.verdict.overall_score if self.verdict else self._deterministic_score()

    def _deterministic_score(self) -> int:
        """Used when no judge ran: `--no-judge`, a protocol script, or a judge that could
        not be reached.

        A judge that never answered is not a failed kiosk. The checks still ran, so the
        score is what the rules alone can say: full marks when every applicable check
        passed, a partial when only soft checks did not. The runner sets `result.error` in
        the unreachable case, and `ScenarioResult.status` reads that as a FAIL regardless of
        the number, so a harness problem is still visible and never quietly passes -- it
        just no longer reports as though the kiosk mishandled the session.

        A judge that ran and returned an unusable answer is a different thing: the runner
        records a `JudgeVerdict.unavailable` scoring 1, which never lands here.
        """
        if self.hard_failures:
            return HARD_FAILURE_SCORE_CAP
        return 7 if self.soft_failures else 10

    @property
    def was_capped(self) -> bool:
        return bool(self.hard_failures) and self.raw_score > HARD_FAILURE_SCORE_CAP

    @property
    def score_cap_reason(self) -> str | None:
        """Derived rather than stored: a cap that has to be recorded by a separate step
        is a cap that can be forgotten by one."""
        if not self.was_capped:
            return None
        return ", ".join(check.name for check in self.hard_failures)

    @property
    def status(self) -> Literal["PASS", "PARTIAL", "FAIL"]:
        """Bands mirror the judge's own rubric: 7+ is correct handling, 4-6 is acceptable
        with real problems, 1-3 is a failure. A hard check failure or a crash is a FAIL
        outright, regardless of the number."""
        if self.hard_failures or self.error:
            return "FAIL"
        if self.score >= PASS_THRESHOLD:
            return "PASS"
        return "PARTIAL" if self.score >= PARTIAL_THRESHOLD else "FAIL"

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def _check_summary(self) -> str:
        """Stands in for the judge's prose when no judge ran, so the 'why' column is
        never blank."""
        applicable = self.applicable_checks
        passed = sum(1 for check in applicable if check.passed)
        failed = [check for check in applicable if not check.passed]
        summary = (
            f"No judge ran for this scenario, so it was scored on policy checks alone: "
            f"{passed} of {len(applicable)} applicable checks passed."
        )
        if failed:
            details = "; ".join(f"{check.name} ({check.detail})" for check in failed)
            summary += f" Failed: {details}."
        return summary

    @property
    def reasoning(self) -> str:
        """The 'why' the report shows -- the judge's own words, prefixed with the cap
        when a policy breach overruled the number it chose."""
        base = self.verdict.reasoning if self.verdict else self._check_summary()
        if self.error:
            return f"The scenario did not complete: {self.error}\n\n{base}"
        if self.was_capped:
            names = ", ".join(check.name for check in self.hard_failures)
            return (
                f"Score capped at {HARD_FAILURE_SCORE_CAP}/10 (judge gave "
                f"{self.raw_score}/10) because these mandatory policy checks failed: "
                f"{names}.\n\n{base}"
            )
        return base


@dataclass(frozen=True, slots=True)
class RunSummary:
    total: int
    passed: int
    partial: int
    failed: int
    average_score: float
    pass_rate: float
    checks_total: int
    checks_passed: int
    hard_failures: int
    duration_seconds: int

    @property
    def check_pass_rate(self) -> float:
        return (self.checks_passed / self.checks_total * 100) if self.checks_total else 0.0


def summarize(results: list[ScenarioResult], *, duration_seconds: int = 0) -> RunSummary:
    total = len(results)
    passed = sum(1 for result in results if result.status == "PASS")
    partial = sum(1 for result in results if result.status == "PARTIAL")
    applicable = [check for result in results for check in result.applicable_checks]
    checks_passed = sum(1 for check in applicable if check.passed)
    return RunSummary(
        total=total,
        passed=passed,
        partial=partial,
        failed=total - passed - partial,
        average_score=(sum(result.score for result in results) / total) if total else 0.0,
        pass_rate=(passed / total * 100) if total else 0.0,
        checks_total=len(applicable),
        checks_passed=checks_passed,
        hard_failures=sum(len(result.hard_failures) for result in results),
        duration_seconds=duration_seconds,
    )


@dataclass(frozen=True, slots=True)
class ScoreSpread:
    scenario: str
    runs: int
    mean: float
    lowest: int
    highest: int

    @property
    def spread(self) -> int:
        return self.highest - self.lowest


def score_spreads(results: list[ScenarioResult]) -> list[ScoreSpread]:
    """Per-scenario mean and range, for `--repeat` runs.

    Only scenarios actually run more than once appear. The spread is the point of the
    exercise: a scenario that scores 9, 4, 8 across three runs is not an 7.0 -- it is
    unstable, and that is a finding about the kiosk (or about the scenario) rather than a
    number to average away. Widest spread first.
    """
    buckets: dict[str, list[int]] = {}
    for result in results:
        buckets.setdefault(result.scenario, []).append(result.score)
    spreads = [
        ScoreSpread(
            scenario=scenario,
            runs=len(scores),
            mean=sum(scores) / len(scores),
            lowest=min(scores),
            highest=max(scores),
        )
        for scenario, scores in buckets.items()
        if len(scores) > 1
    ]
    return sorted(spreads, key=lambda item: (-item.spread, item.scenario))


@dataclass(frozen=True, slots=True)
class TurnLatency:
    """How long the customer waits, per kiosk operation."""

    tool: str
    calls: int
    p50_ms: int
    p95_ms: int
    max_ms: int


def turn_latencies(results: list[ScenarioResult]) -> list[TurnLatency]:
    """Percentiles per API operation across every exchange in the run.

    The scorecard graded correctness and said nothing about waiting, so a kiosk could score
    9.2/10 while leaving a person in silence for six seconds a turn -- which is what a live
    session measured on 2026-08-19. Every exchange already carries `latency_ms`; this only
    surfaces it. p95, not the mean: the slow turns are the ones people remember.
    """
    buckets: dict[str, list[int]] = {}
    for result in results:
        for exchange in result.exchanges:
            if exchange.latency_ms > 0:
                buckets.setdefault(exchange.tool, []).append(exchange.latency_ms)

    def percentile(values: list[int], fraction: float) -> int:
        # Nearest-rank: with a handful of samples per operation, interpolating between two
        # measurements would invent a latency nothing actually took.
        rank = max(1, math.ceil(fraction * len(values)))
        return values[rank - 1]

    latencies = [
        TurnLatency(
            tool=tool,
            calls=len(values),
            p50_ms=percentile(sorted(values), 0.50),
            p95_ms=percentile(sorted(values), 0.95),
            max_ms=max(values),
        )
        for tool, values in buckets.items()
    ]
    return sorted(latencies, key=lambda item: -item.p95_ms)


def group_averages(results: list[ScenarioResult]) -> dict[str, float]:
    buckets: dict[str, list[int]] = {}
    for result in results:
        buckets.setdefault(result.group, []).append(result.score)
    return {group: sum(scores) / len(scores) for group, scores in buckets.items()}
