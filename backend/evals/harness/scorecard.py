"""Renders a list of EvalResult into a scorecard -- markdown for humans/CI artifacts,
dict for JSON output."""

from harness.evaluator import EvalResult


def to_dict(results: list[EvalResult]) -> dict:
    total_checks = sum(len(result.checks) for result in results)
    passed_checks = sum(1 for result in results for check in result.checks if check.passed)
    return {
        "personas_total": len(results),
        "personas_passed": sum(1 for result in results if result.passed),
        "checks_total": total_checks,
        "checks_passed": passed_checks,
        "results": [
            {
                "persona": result.persona,
                "final_status": result.final_status,
                "passed": result.passed,
                "checks": [
                    {"name": check.name, "passed": check.passed, "detail": check.detail}
                    for check in result.checks
                ],
            }
            for result in results
        ],
    }


def to_markdown(results: list[EvalResult]) -> str:
    summary = to_dict(results)
    lines = [
        "# Scorecard de evaluación de la política de orquestación",
        "",
        f"Personas: {summary['personas_passed']}/{summary['personas_total']} aprobadas. "
        f"Verificaciones: {summary['checks_passed']}/{summary['checks_total']} aprobadas.",
        "",
    ]
    for result in results:
        icon = "✅" if result.passed else "❌"
        lines.append(f"## {icon} {result.persona} (`{result.final_status}`)")
        lines.append("")
        lines.append("| Verificación | Resultado | Detalle |")
        lines.append("| --- | --- | --- |")
        for check in result.checks:
            check_icon = "✅" if check.passed else "❌"
            lines.append(f"| {check.name} | {check_icon} | {check.detail} |")
        lines.append("")
    return "\n".join(lines)
