"""Markdown scorecard -- the terminal output and the CI artifact.

Deliberately compact: the dashboard is where a run is read in detail, so this view
answers only "did it pass, what scored badly, and why" without the transcripts.
"""

from harness.scoring import (
    ScenarioResult,
    group_averages,
    score_spreads,
    summarize,
    turn_latencies,
)

STATUS_MARK = {"PASS": "[PASS]", "PARTIAL": "[PART]", "FAIL": "[FAIL]"}


def to_markdown(results: list[ScenarioResult], *, duration_seconds: int = 0) -> str:
    summary = summarize(results, duration_seconds=duration_seconds)
    lines = [
        "# Kiosk orchestration evaluation",
        "",
        f"Scenarios: {summary.passed}/{summary.total} passed "
        f"({summary.pass_rate:.0f}% pass rate, {summary.partial} partial, "
        f"{summary.failed} failed).",
        f"Average score: {summary.average_score:.1f}/10.",
        f"Checks: {summary.checks_passed}/{summary.checks_total} passed "
        f"({summary.hard_failures} hard policy failures).",
        "",
        "| Scenario | Group | Score | Verdict | Expected | Actual |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result.scenario} | {result.group} | {result.score}/10 | "
            f"{STATUS_MARK[result.status]} | {result.expected_summary} | "
            f"{result.actual_summary} |"
        )

    averages = group_averages(results)
    if averages:
        lines.extend(["", "## Average score by group", ""])
        for group, average in sorted(averages.items(), key=lambda item: item[1]):
            lines.append(f"- {group}: {average:.1f}/10")

    spreads = score_spreads(results)
    if spreads:
        lines.extend(
            [
                "",
                "## Score variance across repetitions",
                "",
                "| Scenario | Runs | Mean | Range | Spread |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in spreads:
            lines.append(
                f"| {item.scenario} | {item.runs} | {item.mean:.1f} | "
                f"{item.lowest}-{item.highest} | {item.spread} |"
            )

    latencies = turn_latencies(results)
    if latencies:
        lines.extend(
            [
                "",
                "## How long the customer waits",
                "",
                "Wall-clock per API call. A voice turn also pays speech detection and "
                "text-to-speech on top of these numbers.",
                "",
                "| Operation | Calls | p50 | p95 | Max |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in latencies:
            lines.append(
                f"| {item.tool} | {item.calls} | {item.p50_ms / 1000:.1f}s | "
                f"{item.p95_ms / 1000:.1f}s | {item.max_ms / 1000:.1f}s |"
            )

    problems = [result for result in results if result.status != "PASS"]
    if problems:
        lines.extend(["", "## What went wrong", ""])
        for result in problems:
            lines.append(f"### {STATUS_MARK[result.status]} {result.scenario} ({result.score}/10)")
            lines.append("")
            for check in result.hard_failures:
                lines.append(f"- **{check.name}** (hard): {check.detail}")
            for check in result.soft_failures:
                lines.append(f"- {check.name} (soft): {check.detail}")
            if result.verdict:
                for failure in result.verdict.failures:
                    lines.append(f"- judge: {failure}")
            lines.extend(["", result.reasoning, ""])
    return "\n".join(lines)
