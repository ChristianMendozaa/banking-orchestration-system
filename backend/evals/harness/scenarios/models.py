"""The scenario model.

A **scenario** is one test case: a situation, the way the customer expresses it, and the
outcome the orchestration policy is supposed to produce. A **persona style** is only how
that customer speaks -- distressed, terse, rambling -- and is deliberately separate so the
same situation can be re-tested through a different mouth.

`ExpectedOutcome` is the single source of truth for both scoring paths. The deterministic
evaluator turns its fields into HARD checks; the judge receives the same object as the
rubric it grades against. Nothing about what "correct" means lives in two places.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from harness.evaluator import CheckResult
    from harness.session import ConversationSession

ExpectationChecks = Callable[["ConversationSession", dict], list["CheckResult"]]
ProtocolScript = Callable[["ConversationSession"], Awaitable[list["CheckResult"]]]


@dataclass(frozen=True, slots=True)
class PersonaStyle:
    name: str
    instruction: str


# How the simulated customer talks. The kiosk has to cope with all of it: a real branch
# queue is not full of articulate people who state their need in one clean sentence.
ANGUSTIADO = PersonaStyle(
    "angustiado",
    "Hablas con angustia y prisa, con frases cortas y entrecortadas. Estas asustado.",
)
CALMADO = PersonaStyle(
    "calmado",
    "Hablas con calma y claridad, sin dramatismo, en una o dos frases.",
)
APURADO = PersonaStyle(
    "apurado",
    "Tienes prisa. Respondes con la menor cantidad de palabras posible y te impacientas.",
)
PARCO = PersonaStyle(
    "parco",
    "Respondes con monosilabos: 'si', 'no', 'no se'. Casi nunca das detalles por tu cuenta.",
)
ADULTO_MAYOR = PersonaStyle(
    "adulto_mayor",
    "Eres una persona mayor, poco familiarizada con la tecnologia. Hablas despacio, das "
    "rodeos, mezclas detalles irrelevantes y a veces pides que te repitan las cosas.",
)
TECNICO = PersonaStyle(
    "tecnico",
    "Te expresas con precision y usas terminologia bancaria correcta.",
)
HOSTIL = PersonaStyle(
    "hostil",
    "Estas molesto y lo demuestras. Reclamas, interrumpes y usas un tono cortante "
    "(sin groserias explicitas).",
)
DISPERSO = PersonaStyle(
    "disperso",
    "Te cuesta explicarte. Divagas, empiezas una idea y saltas a otra, y recien al final "
    "mencionas lo que realmente necesitas.",
)


@dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    """What correct handling looks like for one scenario.

    Every field left as `None` means "this scenario does not constrain it" -- the
    corresponding check reports as not-applicable instead of silently passing.
    """

    # Tuples mean "any of these is acceptable" -- used where the policy genuinely allows
    # more than one correct reading (e.g. an informational question about a sensitive
    # topic may land as CONSULTA_GENERAL or as BLOQUEO_TARJETA).
    category: tuple[str, ...] | None = None
    consultation_level: tuple[str, ...] | None = None
    priority: tuple[str, ...] | None = None
    resolution_type: str | None = None
    grounding_status: tuple[str, ...] | None = None
    # True: an automatic answer must carry citations. False: there must be none.
    requires_citations: bool | None = None
    # Terminal identification status, or "NONE" for a case that must never ask for a CI.
    identification: str | None = None
    clarifications: tuple[int, int] | None = None  # inclusive (min, max)
    corrections: int | None = None
    pii_types: tuple[str, ...] = ()
    # Literal strings the customer said that must never come back out of the kiosk.
    forbidden_echo: tuple[str, ...] = ()
    # English, for the judge: the qualitative bar this scenario is really about.
    policy_notes: str = ""


# A real identity-card number from `backend/seed/operational_seed.json`, and the default
# for every persona: someone walking into a branch has their ID on them. Scenarios about a
# *wrong* or *missing* card say so explicitly, and `tests/test_scenarios.py` asserts this
# value really is in the client reference registry.
DEFAULT_IDENTIFIER = "6735666"


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    goal: str
    expected: ExpectedOutcome
    tags: tuple[str, ...] = ()
    style: PersonaStyle = CALMADO
    # The CI the customer hands over when asked. `None` means the customer genuinely has
    # none to give -- a case worth testing, but never the default.
    identifier: str | None = DEFAULT_IDENTIFIER
    preferential_attention: bool = False
    expectation_checks: ExpectationChecks | None = None
    # Set only by the `protocol` group: drives the API directly, with no LLM customer.
    script: ProtocolScript | None = None
    # A short English description of the situation, for the dashboard and the judge.
    description: str = ""

    @property
    def group(self) -> str:
        """First tag, used to group rows and bars in the dashboard."""
        return self.tags[0] if self.tags else "otros"


@dataclass(frozen=True, slots=True)
class ScenarioCatalog:
    scenarios: tuple[Scenario, ...] = field(default=())

    def filter(
        self, *, names: list[str] | None = None, tags: list[str] | None = None
    ) -> list[Scenario]:
        selected = list(self.scenarios)
        if names:
            wanted = set(names)
            selected = [s for s in selected if s.name in wanted]
        if tags:
            wanted = set(tags)
            selected = [s for s in selected if wanted & set(s.tags)]
        return selected
