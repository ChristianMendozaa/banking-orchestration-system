"""Machine-readable dump of a run.

Complete on purpose -- transcripts, per-dimension judge scores, every check with its
severity and applicability -- so a run can be re-analysed, diffed against another run, or
loaded into a notebook without re-running the (billed) evaluation.
"""

from harness.scoring import ScenarioResult, group_averages, summarize


def to_dict(results: list[ScenarioResult], *, metadata: dict | None = None) -> dict:
    summary = summarize(results, duration_seconds=(metadata or {}).get("duration_seconds", 0))
    return {
        "metadata": metadata or {},
        "summary": {
            "scenarios_total": summary.total,
            "scenarios_passed": summary.passed,
            "scenarios_partial": summary.partial,
            "scenarios_failed": summary.failed,
            "average_score": round(summary.average_score, 2),
            "pass_rate": round(summary.pass_rate, 1),
            "checks_total": summary.checks_total,
            "checks_passed": summary.checks_passed,
            "hard_failures": summary.hard_failures,
            "average_score_by_group": {
                group: round(value, 2) for group, value in group_averages(results).items()
            },
        },
        "results": [_result_to_dict(result) for result in results],
    }


def _result_to_dict(result: ScenarioResult) -> dict:
    verdict = result.verdict
    return {
        "scenario": result.scenario,
        "group": result.group,
        "tags": result.tags,
        "description": result.description,
        "repetition": result.repetition,
        "session_id": result.session_id,
        "status": result.status,
        "score": result.score,
        "raw_judge_score": result.raw_score,
        "score_cap_reason": result.score_cap_reason,
        "final_status": result.final_status,
        "expected": result.expected_summary,
        "actual": result.actual_summary,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "reasoning": result.reasoning,
        "judge": (
            {
                "overall_score": verdict.overall_score,
                "verdict": verdict.verdict,
                "reasoning": verdict.reasoning,
                "failures": verdict.failures,
                "strengths": verdict.strengths,
                "dimensions": {
                    name: {"score": dimension.score, "reasoning": dimension.reasoning}
                    for name, dimension in verdict.dimensions.items()
                },
            }
            if verdict
            else None
        ),
        "checks": [
            {
                "name": check.name,
                "severity": check.severity,
                "applicable": check.applicable,
                "passed": check.passed,
                "detail": check.detail,
            }
            for check in result.checks
        ],
        "transcript": [
            {
                "step": exchange.index + 1,
                "action": exchange.tool,
                "customer": exchange.customer_text,
                "kiosk": exchange.kiosk_speech,
                "latency_ms": exchange.latency_ms,
                "error": exchange.error,
            }
            for exchange in result.exchanges
        ],
    }
