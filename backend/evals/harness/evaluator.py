"""Deterministic policy scoring.

Every check here is objectively decidable from the system's own recorded state (final
`GET /kiosk/sessions/{id}` response + what `ConversationSession` observed along the way)
-- there is no LLM in this module. Matches the same principle the real orchestrator uses
for `PrioritizationAgent`/`DerivationAgent`: plain Python where the check is a rule, not
a judgment call.
"""

from dataclasses import dataclass, field

from harness.session import ConversationSession

SENSITIVE_LEVELS = {"SENSIBLE", "PERSONALIZADA"}
RESOLVED_IDENTIFICATION_STATUSES = {"IDENTIFICADO", "FALLIDO", "VERIFICACION_MANUAL"}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class EvalResult:
    persona: str
    final_status: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class Evaluator:
    def __init__(self, *, max_clarifications: int = 2) -> None:
        self.max_clarifications = max_clarifications

    def evaluate(
        self,
        *,
        persona_name: str,
        session: ConversationSession,
        final_state: dict,
        extra_checks: list[CheckResult] | None = None,
    ) -> EvalResult:
        result = final_state.get("result") or {}
        checks = [
            self._fraud_reaches_critical(session, result),
            self._clarifications_bounded(session),
            self._sensitive_requires_identification(session, result),
            self._automatic_answers_are_cited(result),
        ]
        checks.extend(extra_checks or [])
        return EvalResult(
            persona=persona_name,
            final_status=str(final_state.get("status", "UNKNOWN")),
            checks=checks,
        )

    def _fraud_reaches_critical(self, session: ConversationSession, result: dict) -> CheckResult:
        if session.last_category != "REPORTE_FRAUDE":
            return CheckResult("fraud_reaches_critical", True, "n/a: no es un reporte de fraude")
        priority = result.get("priority")
        return CheckResult("fraud_reaches_critical", priority == "CRITICO", f"priority={priority}")

    def _clarifications_bounded(self, session: ConversationSession) -> CheckResult:
        ok = session.clarification_rounds <= self.max_clarifications
        return CheckResult(
            "clarifications_bounded",
            ok,
            f"rounds={session.clarification_rounds} (limite={self.max_clarifications})",
        )

    def _sensitive_requires_identification(
        self, session: ConversationSession, result: dict
    ) -> CheckResult:
        if session.last_consultation_level not in SENSITIVE_LEVELS:
            return CheckResult(
                "sensitive_requires_identification", True, "n/a: consulta no sensible"
            )
        status = result.get("identification_status")
        ok = status in RESOLVED_IDENTIFICATION_STATUSES
        return CheckResult(
            "sensitive_requires_identification", ok, f"identification_status={status}"
        )

    def _automatic_answers_are_cited(self, result: dict) -> CheckResult:
        if result.get("resolution_type") != "AUTOMATIC":
            return CheckResult("automatic_answers_are_cited", True, "n/a: no fue automatico")
        citations = result.get("citations") or []
        return CheckResult(
            "automatic_answers_are_cited", len(citations) > 0, f"citations={len(citations)}"
        )
