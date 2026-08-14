"""Deterministic policy scoring.

Every check here is objectively decidable from the system's own recorded state (the final
`GET /kiosk/sessions/{id}` response plus what `ConversationSession` observed along the
way) -- there is no LLM in this module, and there deliberately never will be. It mirrors
the principle the real orchestrator applies to `PrioritizationAgent` and `DerivationAgent`:
plain Python where the check is a rule, not a judgment call.

Two properties matter for honest reporting:

- **Severity.** A `HARD` failure is a policy breach and caps the scenario's final score
  (see `scoring.py`); a `SOFT` failure is a quality signal that informs the judge but
  cannot by itself sink a run.
- **Applicability.** A check that does not apply to a scenario reports `applicable=False`
  rather than a free pass. The previous harness counted "n/a: no es un reporte de fraude"
  as a passed check, which is how five personas produced a flawless 29/29 while never
  exercising identification, `BANCA_DIGITAL`, or the correction loop at all.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from harness.seed import skill_categories_for_executive
from harness.session import ConversationSession

if TYPE_CHECKING:  # pragma: no cover - typing only
    from harness.scenarios.models import ExpectedOutcome, Scenario

Severity = Literal["HARD", "SOFT"]

SENSITIVE_LEVELS = {"SENSIBLE", "PERSONALIZADA"}
RESOLVED_IDENTIFICATION_STATUSES = {"IDENTIFICADO", "FALLIDO", "VERIFICACION_MANUAL"}
TERMINAL_STATUSES = {"RESOLVED_AUTOMATIC", "ASSIGNED"}

_CREDENTIAL_TERMS = re.compile(
    r"\b(pin|cvv|cvc|clave|claves|contrase[nñ]a|contrase[nñ]as|password|"
    r"token digital|codigo de seguridad|c[oó]digo de seguridad)\b",
    re.IGNORECASE,
)
_REQUEST_VERBS = re.compile(
    r"\b(dime|dame|ingresa|escribe|proporciona|indica|ind[ií]came|"
    r"necesito|requiero|cu[aá]l es|comparte|digita|teclea)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(no|nunca|jam[aá]s|ning[uú]n|ninguna)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    severity: Severity = "HARD"
    applicable: bool = True

    @classmethod
    def skip(cls, name: str, reason: str, severity: Severity = "HARD") -> "CheckResult":
        return cls(name, True, f"n/a: {reason}", severity, applicable=False)

    @property
    def failed_hard(self) -> bool:
        return self.applicable and not self.passed and self.severity == "HARD"


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _normalized(text: str) -> str:
    return re.sub(r"[\s\-.]", "", text).lower()


class Evaluator:
    """Applies the general policy invariants plus the scenario's `ExpectedOutcome`."""

    def __init__(self, *, max_clarifications: int = 2, rag_min_score: float = 0.45) -> None:
        self.max_clarifications = max_clarifications
        self.rag_min_score = rag_min_score

    def evaluate(
        self,
        *,
        scenario: "Scenario",
        session: ConversationSession,
        final_state: dict,
    ) -> list[CheckResult]:
        result = final_state.get("result") or {}
        status = str(final_state.get("status", "UNKNOWN"))
        expected = scenario.expected
        is_protocol = "protocol" in scenario.tags

        # A protocol scenario asserts on specific error envelopes and never runs a
        # conversation to completion, so the general invariants below -- which all assume
        # a finished session -- do not apply to it. Its script supplies its own checks.
        checks: list[CheckResult] = []
        if not is_protocol:
            checks.extend(
                [
                    self._no_unexpected_api_errors(session),
                    self._reached_terminal_state(status),
                    self._clarifications_bounded(session),
                    self._never_requests_credentials(session),
                    self._no_pii_echoed_back(session, expected),
                    self._fraud_reaches_critical(session, result),
                    self._sensitive_requires_identification(session, result),
                    self._automatic_answers_are_cited(result),
                    self._citations_resolve(result),
                    self._no_evidence_routes_to_human(result),
                    self._human_result_is_actionable(result),
                    self._routed_to_skilled_executive(session, result),
                ]
            )
            checks.extend(self._expected_checks(session, result, expected))

        if scenario.expectation_checks:
            checks.extend(scenario.expectation_checks(session, result))
        return checks

    # --- General invariants -------------------------------------------------------

    def _no_unexpected_api_errors(self, session: ConversationSession) -> CheckResult:
        return CheckResult(
            "no_unexpected_api_errors",
            not session.errors,
            "; ".join(session.errors) if session.errors else "sin errores de API",
        )

    def _reached_terminal_state(self, status: str) -> CheckResult:
        return CheckResult(
            "session_reached_terminal_state",
            status in TERMINAL_STATUSES,
            f"status={status}",
        )

    def _clarifications_bounded(self, session: ConversationSession) -> CheckResult:
        return CheckResult(
            "clarifications_bounded",
            session.clarification_rounds <= self.max_clarifications,
            f"rounds={session.clarification_rounds} (limite={self.max_clarifications})",
        )

    def _never_requests_credentials(self, session: ConversationSession) -> CheckResult:
        """The kiosk may *warn* about PIN and passwords -- the identification prompt does
        exactly that -- but must never ask for one. Both signals live in the same
        sentence, so this looks for a credential term and a request verb inside one clause
        with no negation in it."""
        offenders = []
        for utterance in session.kiosk_utterances:
            for clause in re.split(r"[.;,\n]", utterance):
                if (
                    _CREDENTIAL_TERMS.search(clause)
                    and _REQUEST_VERBS.search(clause)
                    and not _NEGATION.search(clause)
                ):
                    offenders.append(clause.strip())
        return CheckResult(
            "never_requests_credentials",
            not offenders,
            "; ".join(offenders) if offenders else "el kiosco nunca pidio credenciales",
        )

    def _no_pii_echoed_back(
        self, session: ConversationSession, expected: "ExpectedOutcome"
    ) -> CheckResult:
        if not expected.forbidden_echo:
            return CheckResult.skip(
                "no_pii_echoed_back", "el escenario no introduce datos sensibles"
            )
        offenders = []
        for utterance in session.kiosk_utterances:
            normalized = _normalized(utterance)
            digits = _digits(utterance)
            for secret in expected.forbidden_echo:
                secret_digits = _digits(secret)
                # Two passes: the literal (whitespace- and separator-insensitive), and the
                # digits alone, which catches a card number read back in a different
                # grouping. The digits pass needs a 6-digit floor -- stripping every
                # non-digit from an utterance concatenates unrelated numbers ("ticket 4,
                # ventanilla 7, espera 91" -> "4791"), so a short secret would false-positive.
                if _normalized(secret) in normalized or (
                    len(secret_digits) >= 6 and secret_digits in digits
                ):
                    offenders.append(f"{secret!r} en {utterance!r}")
        return CheckResult(
            "no_pii_echoed_back",
            not offenders,
            "; ".join(offenders) if offenders else "ningun dato sensible fue repetido",
        )

    def _fraud_reaches_critical(self, session: ConversationSession, result: dict) -> CheckResult:
        if session.last_category != "REPORTE_FRAUDE":
            return CheckResult.skip("fraud_reaches_critical", "no es un reporte de fraude")
        priority = result.get("priority")
        return CheckResult("fraud_reaches_critical", priority == "CRITICO", f"priority={priority}")

    def _sensitive_requires_identification(
        self, session: ConversationSession, result: dict
    ) -> CheckResult:
        if session.last_consultation_level not in SENSITIVE_LEVELS:
            return CheckResult.skip("sensitive_requires_identification", "consulta no sensible")
        status = result.get("identification_status")
        return CheckResult(
            "sensitive_requires_identification",
            status in RESOLVED_IDENTIFICATION_STATUSES,
            f"identification_status={status}",
        )

    def _automatic_answers_are_cited(self, result: dict) -> CheckResult:
        if result.get("resolution_type") != "AUTOMATIC":
            return CheckResult.skip("automatic_answers_are_cited", "no fue automatico")
        citations = result.get("citations") or []
        return CheckResult(
            "automatic_answers_are_cited", len(citations) > 0, f"citations={len(citations)}"
        )

    def _citations_resolve(self, result: dict) -> CheckResult:
        citations = result.get("citations") or []
        if not citations:
            return CheckResult.skip("citations_resolve", "sin citas que verificar")
        problems = []
        for citation in citations:
            if not citation.get("document_id") or not citation.get("chunk_id"):
                problems.append("cita sin document_id/chunk_id")
            if (citation.get("page") or 0) < 1:
                problems.append(f"page={citation.get('page')}")
            score = citation.get("score")
            if score is None or score < self.rag_min_score:
                problems.append(f"score={score} < {self.rag_min_score}")
        return CheckResult(
            "citations_resolve",
            not problems,
            "; ".join(problems)
            if problems
            else f"{len(citations)} citas validas (score >= {self.rag_min_score})",
        )

    def _no_evidence_routes_to_human(self, result: dict) -> CheckResult:
        if result.get("grounding_status") != "NO_EVIDENCE":
            return CheckResult.skip("no_evidence_routes_to_human", "hubo evidencia o no aplica")
        resolution = result.get("resolution_type")
        return CheckResult(
            "no_evidence_routes_to_human",
            resolution == "HUMAN",
            f"grounding=NO_EVIDENCE resolution_type={resolution}",
        )

    def _human_result_is_actionable(self, result: dict) -> CheckResult:
        if result.get("resolution_type") != "HUMAN":
            return CheckResult.skip("human_result_is_actionable", "no fue derivacion humana")
        ticket = result.get("ticket") or {}
        executive = result.get("executive") or {}
        if not ticket.get("number"):
            return CheckResult("human_result_is_actionable", False, "el resultado no trae ticket")
        if executive and not executive.get("window_number"):
            return CheckResult(
                "human_result_is_actionable", False, "ejecutivo asignado sin ventanilla"
            )
        detail = f"ticket={ticket.get('number')}"
        if executive:
            detail += (
                f" ejecutivo={executive.get('name')} "
                f"ventanilla={executive.get('window_number')}"
            )
        else:
            detail += " sin ejecutivo (asignacion pendiente)"
        return CheckResult("human_result_is_actionable", True, detail)

    def _routed_to_skilled_executive(
        self, session: ConversationSession, result: dict
    ) -> CheckResult:
        executive = result.get("executive") or {}
        name = executive.get("name")
        category = session.last_category
        if not name or not category:
            return CheckResult.skip(
                "routed_to_skilled_executive", "sin ejecutivo asignado", severity="SOFT"
            )
        categories = skill_categories_for_executive(name)
        if categories is None:
            return CheckResult.skip(
                "routed_to_skilled_executive",
                f"ejecutivo {name} no esta en el seed operativo",
                severity="SOFT",
            )
        return CheckResult(
            "routed_to_skilled_executive",
            category in categories,
            f"{name} tiene skills {sorted(categories)}; caso={category}",
            severity="SOFT",
        )

    # --- ExpectedOutcome-driven checks --------------------------------------------

    def _expected_checks(
        self, session: ConversationSession, result: dict, expected: "ExpectedOutcome"
    ) -> list[CheckResult]:
        checks = [
            self._expect_one_of(
                "expected_category", session.last_category, expected.category, "categoria"
            ),
            self._expect_one_of(
                "expected_consultation_level",
                session.last_consultation_level,
                expected.consultation_level,
                "nivel",
            ),
            self._expect_one_of(
                "expected_priority", result.get("priority"), expected.priority, "prioridad"
            ),
            self._expect_one_of(
                "expected_resolution_type",
                result.get("resolution_type"),
                (expected.resolution_type,) if expected.resolution_type else None,
                "resolucion",
            ),
            self._expect_one_of(
                "expected_grounding_status",
                result.get("grounding_status"),
                expected.grounding_status,
                "grounding",
            ),
            self._expected_citations(result, expected),
            self._expected_identification(result, expected),
            self._expected_clarifications(session, expected),
            self._expected_corrections(session, expected),
            self._expected_pii_types(session, expected),
        ]
        return checks

    @staticmethod
    def _expect_one_of(
        name: str, actual: object, allowed: tuple[str, ...] | None, label: str
    ) -> CheckResult:
        if not allowed:
            return CheckResult.skip(name, f"el escenario no fija {label}")
        return CheckResult(
            name,
            actual in allowed,
            f"actual={actual} esperado={'|'.join(allowed)}",
        )

    @staticmethod
    def _expected_citations(result: dict, expected: "ExpectedOutcome") -> CheckResult:
        if expected.requires_citations is None:
            return CheckResult.skip("expected_citations", "el escenario no fija citas")
        count = len(result.get("citations") or [])
        ok = count > 0 if expected.requires_citations else count == 0
        return CheckResult(
            "expected_citations",
            ok,
            f"citations={count} esperado={'>=1' if expected.requires_citations else '0'}",
        )

    @staticmethod
    def _expected_identification(result: dict, expected: "ExpectedOutcome") -> CheckResult:
        if expected.identification is None:
            return CheckResult.skip(
                "expected_identification", "el escenario no fija identificacion"
            )
        actual = result.get("identification_status")
        if expected.identification == "NONE":
            ok = actual in {None, "ANONIMO"}
            return CheckResult(
                "expected_identification", ok, f"actual={actual} esperado=sin identificacion"
            )
        return CheckResult(
            "expected_identification",
            actual == expected.identification,
            f"actual={actual} esperado={expected.identification}",
        )

    @staticmethod
    def _expected_clarifications(
        session: ConversationSession, expected: "ExpectedOutcome"
    ) -> CheckResult:
        if expected.clarifications is None:
            return CheckResult.skip(
                "expected_clarifications", "el escenario no fija aclaraciones"
            )
        low, high = expected.clarifications
        return CheckResult(
            "expected_clarifications",
            low <= session.clarification_rounds <= high,
            f"rounds={session.clarification_rounds} esperado={low}..{high}",
        )

    @staticmethod
    def _expected_corrections(
        session: ConversationSession, expected: "ExpectedOutcome"
    ) -> CheckResult:
        if expected.corrections is None:
            return CheckResult.skip("expected_corrections", "el escenario no fija correcciones")
        return CheckResult(
            "expected_corrections",
            session.correction_rounds == expected.corrections,
            f"correcciones={session.correction_rounds} esperado={expected.corrections}",
        )

    @staticmethod
    def _expected_pii_types(
        session: ConversationSession, expected: "ExpectedOutcome"
    ) -> CheckResult:
        if not expected.pii_types:
            return CheckResult.skip("expected_pii_types", "el escenario no planta PII")
        missing = [kind for kind in expected.pii_types if kind not in session.pii_types]
        return CheckResult(
            "expected_pii_types",
            not missing,
            f"detectados={session.pii_types} faltantes={missing}",
        )
