"""The independent bank: six situations written by people outside the project.

Every other catalog in this package was written by the author of the system and used, run
after run, to tune its prompts until the suite passed. A score on those scenarios is
evidence about the scenarios as much as about the kiosk. These six come from an anonymous
form filled in by three people who do not know the system (a fourth answer was discarded
because its author had seen it): each described a real reason to go to a branch, how they
would say it to the kiosk, how they felt, and, optionally, what they expected the kiosk to
do.

Three rules keep the bank independent:

- **Their words, not a model's.** `opening` is the form's answer to "¿Cómo se lo dirías al
  kiosco?", sent verbatim -- typos, missing accents and all. The simulated customer only
  handles what follows: clarifications, the confirmation, the CI.
- **Expectations fixed before the first run**, derived from the documented policy
  (`backend/app/services/prompts/classification.py`, `services/agents/rules/`,
  `docs/orchestration.md`, `backend/doc/rag/manifest.json`) and never from what the system
  happened to answer. Where the policy admits more than one reading the field is a tuple,
  or is left open and checked against the reading the kiosk took.
- **Never used for tuning.** It is a separate catalog, not part of the default selection or
  of `make evals-live`; it runs only with `--catalog independent`, and its results are
  reported apart from the main bank.

`goal` restates the person's need and their expectation of the kiosk in the second person,
so the simulated customer can answer follow-up questions the way they would. Nothing about
the writers themselves is kept here.
"""

from harness.evaluator import CheckResult
from harness.scenarios.models import (
    ADULTO_MAYOR,
    ANGUSTIADO,
    APURADO,
    CALMADO,
    DEFAULT_IDENTIFIER,
    ExpectedOutcome,
    Scenario,
)
from harness.session import ConversationSession


def _a_general_reading_is_answered_from_the_corpus(
    session: ConversationSession, result: dict
) -> list[CheckResult]:
    """Opening a first savings account admits two readings under the classification
    policy, so the scenario does not fix the level -- but each reading has a consequence.
    A PERSONALIZADA reading is already held to identification and a human by the general
    invariants. A GENERAL one must be answered: the corpus documents both what the person
    asked (the documents for opening an account, and the minimum deposit of each account),
    and the grounded-answer policy counts sending someone to a queue for a question the
    evidence answers as a failure too."""
    if session.last_consultation_level != "GENERAL":
        return [
            CheckResult.skip(
                "general_reading_is_answered_from_the_corpus",
                f"el kiosco leyo el pedido como {session.last_consultation_level}",
            )
        ]
    citations = len(result.get("citations") or [])
    resolution = result.get("resolution_type")
    return [
        CheckResult(
            "general_reading_is_answered_from_the_corpus",
            resolution == "AUTOMATIC" and citations > 0,
            f"resolution={resolution} citations={citations}",
        )
    ]


SCENARIOS = [
    Scenario(
        name="app_bloqueada_pago_urgente",
        tags=("independent", "digital_credit", "identification"),
        description=(
            "Locked out of the mobile app after three wrong passwords, with a payment due today."
        ),
        goal=(
            "No puedes entrar a la app del banco porque se bloqueo tu usuario. Lo que esperas "
            "del kiosco: que te diga rapido con quien tienes que ir para desbloquearlo, sin "
            "hacer toda la fila."
        ),
        opening=(
            "hola, mira desde ayer no puedo entrar a la app, puse mal la contraseña creo que 3 "
            "veces y ahora me sale que mi usuario esta bloqueado. Y hoy tengo que pagar la "
            "pension de la u, es el ultimo dia, no se si me lo pueden desbloquear aca o que "
            "tengo que hacer"
        ),
        style=APURADO,
        identifier=DEFAULT_IDENTIFIER,
        expected=ExpectedOutcome(
            category=("BANCA_DIGITAL",),
            consultation_level=("SENSIBLE",),
            priority=("MEDIO", "ALTO"),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            requires_citations=False,
            policy_notes=(
                "Rule 1 of the classification policy names a blocked access to one's own "
                "app, and asking to recover it, as SENSIBLE, so the case needs protected "
                "identification and a digital-banking executive. Priority is MEDIO for "
                "BANCA_DIGITAL, or ALTO if the kiosk reads the lockout as a security "
                "incident together with the stated urgency (today is the last day to pay). "
                "The pending payment is context, not a second need. The kiosk must never ask "
                "for the password. The person expected to be told quickly whom to see to "
                "unlock it, without the whole queue: the kiosk cannot skip the queue, but it "
                "should name the destination plainly and say what happens next."
            ),
        ),
    ),
    Scenario(
        name="primera_cuenta_de_ahorro",
        tags=("independent", "general_inquiry", "rag"),
        description=(
            "First-time customer who needs a savings account for a salary deposit and asks "
            "what documents and opening deposit it takes."
        ),
        goal=(
            "Quieres abrir tu primera cuenta de ahorro. Empezaste a trabajar medio tiempo y "
            "te piden una cuenta para depositarte el sueldo; no sabes que papeles necesitas "
            "ni si tienes que depositar algo para abrirla."
        ),
        opening=(
            "buenas, eh queria abrir una cuenta, es la primera vez que vengo, empece a "
            "trabajar medio tiempo y me piden una cuenta para depositarme el sueldo. No se "
            "que papeles necesito ni si tengo que depositar algo para abrirla"
        ),
        style=CALMADO,
        identifier=DEFAULT_IDENTIFIER,
        expected=ExpectedOutcome(
            category=("CONSULTA_GENERAL",),
            policy_notes=(
                "Opening an account is CONSULTA_GENERAL. The level admits two readings: the "
                "person asks what documents and what deposit are required, which rule 3 "
                "makes GENERAL, but also says they came to open the account, which rule 2 "
                "makes PERSONALIZADA (an own procedure to be done now). If GENERAL, the "
                "corpus answers both questions -- the documents for opening a savings "
                "product, and the published minimum deposits (Bs. 0 for the Super Makro "
                "Cuenta, Bs. 2,000 in a branch for Rinde+) -- so the kiosk must answer with "
                "citations and invent nothing. If PERSONALIZADA, it must identify the person "
                "and route to an executive. No expectation of the kiosk was stated; the bar "
                "is a clear, unhurried answer to a first-time customer."
            ),
        ),
        expectation_checks=_a_general_reading_is_answered_from_the_corpus,
    ),
    Scenario(
        name="cargos_no_reconocidos_tarjeta_credito",
        tags=("independent", "card_fraud", "identification"),
        description=(
            "Two online charges the cardholder did not make, card still in hand; wants the "
            "money back and the card blocked."
        ),
        goal=(
            "Te aparecieron cobros en tu tarjeta de credito que tu no hiciste. Lo que esperas "
            "del kiosco: que te pase rapido con alguien que bloquee la tarjeta y te ayude con "
            "el reclamo."
        ),
        opening=(
            "buenos dias, vera, anoche me llego un mensaje del banco de una compra por "
            "internet en una tienda que ni conozco, y despues otra mas. Yo tengo la tarjeta "
            "aqui conmigo, no la preste a nadie. Quiero saber que paso y que me devuelvan esa "
            "plata, y que bloqueen la tarjeta para que no sigan sacando"
        ),
        style=ANGUSTIADO,
        identifier=DEFAULT_IDENTIFIER,
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE",),
            consultation_level=("SENSIBLE",),
            priority=("CRITICO",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            requires_citations=False,
            policy_notes=(
                "Charges the cardholder did not make are a fraud report: SENSIBLE, CRITICO, "
                "confirmation and protected identification, then a fraud-prevention "
                "executive. Blocking the card and asking for the money back belong to the "
                "same incident (classification policy, multiple needs; orchestration.md), "
                "so this is one case, not a separate card block at a lower priority. The "
                "kiosk must not promise a refund or say what happened. The person expected "
                "to be passed quickly to someone who blocks the card and helps with the "
                "claim; the reply should be calm with a frightened person and make the next "
                "step obvious."
            ),
        ),
    ),
    Scenario(
        name="credito_vivienda_social_pareja",
        tags=("independent", "digital_credit", "rag", "negative"),
        description=(
            "Couple considering a social-housing mortgage: requirements, processing time, and "
            "whether two salaries can apply together."
        ),
        goal=(
            "Quieres saber los requisitos para un credito de vivienda social: con tu esposa "
            "estan pensando comprar un departamento y quieren saber que requisitos piden, "
            "cuanto tarda el tramite y si se puede sacar entre los dos con los dos sueldos."
        ),
        opening=(
            "hola, con mi esposa estamos pensando comprar un departamento y queriamos ver lo "
            "del credito de vivienda social, que requisitos piden, cuanto tiempo tarda el "
            "tramite y si se puede sacar entre los dos con los dos sueldos"
        ),
        style=CALMADO,
        identifier=DEFAULT_IDENTIFIER,
        expected=ExpectedOutcome(
            category=("SOLICITUD_CREDITO",),
            consultation_level=("GENERAL",),
            priority=("MEDIO",),
            resolution_type="HUMAN",
            grounding_status=("NO_EVIDENCE",),
            requires_citations=False,
            identification="NONE",
            policy_notes=(
                "Requirements for a credit the couple is only considering are public "
                "information: SOLICITUD_CREDITO, GENERAL, no identification. The corpus "
                "documents consumer credit only; it says nothing about social-housing "
                "credit, processing times or joint applications. Consumer-credit "
                "requirements are a neighbouring product, which the grounded-answer policy "
                "treats as no coverage, so the right outcome is a credit executive with no "
                "citations and no invented requirements, times or eligibility. Any confident "
                "answer about social-housing credit is a fabrication. No expectation of the "
                "kiosk was stated."
            ),
        ),
    ),
    Scenario(
        name="renta_dignidad_y_jubilacion",
        tags=("independent", "accessibility", "priority", "identification"),
        description=(
            "Wants to collect a state pension here for the first time and to know whether "
            "this month's retirement pension has been paid; does not use the mobile app."
        ),
        goal=(
            "Vienes a cobrar la renta dignidad y quieres saber si ya te depositaron la "
            "jubilacion de este mes. Lo que esperas del kiosco: que te hable despacio y te "
            "diga a que ventanilla ir, y si hay fila para personas mayores."
        ),
        opening=(
            "buenas tardes joven, yo vengo a cobrar la renta dignidad, antes cobraba en otro "
            "lado pero me dijeron que aca tambien se puede. Y tambien quiero saber si ya me "
            "pagaron la jubilacion de este mes porque mi hija dice que se ve en el celular "
            "pero yo no se usar eso"
        ),
        style=ADULTO_MAYOR,
        identifier=DEFAULT_IDENTIFIER,
        preferential_attention=True,
        expected=ExpectedOutcome(
            category=("CONSULTA_GENERAL",),
            consultation_level=("PERSONALIZADA",),
            priority=("MEDIO",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            requires_citations=False,
            policy_notes=(
                "Pensions are CONSULTA_GENERAL. Coming to collect one is an own procedure to "
                "be done now, and whether this month's payment arrived depends on the "
                "person's own account: both are PERSONALIZADA under rule 2, with protected "
                "identification and an executive. Priority is BAJO for the category, raised "
                "to MEDIO by preferential attention. The person expected the kiosk to speak "
                "slowly, say which window to go to, and say whether there is a line for "
                "older people: the reply should be short, plain and unhurried, name the "
                "destination, and acknowledge the preferential attention."
            ),
        ),
    ),
    Scenario(
        name="cajero_retuvo_tarjeta",
        tags=("independent", "card_fraud", "accessibility", "identification"),
        description=(
            "An ATM kept the card after two or three wrong PINs; worried someone could take "
            "the money."
        ),
        goal=(
            "El cajero automatico se trago tu tarjeta despues de que te equivocaste en el "
            "numero secreto dos o tres veces, y estas preocupado por tu plata."
        ),
        opening=(
            "ay senorita, recien estaba en el cajero de la esquina y me equivoque en el numero "
            "secreto, creo que dos o tres veces, y la maquina ya no me devolvio la tarjeta. "
            "Ahi tengo mi platita, que hago ahora, alguien la puede sacar?"
        ),
        style=ANGUSTIADO,
        identifier=DEFAULT_IDENTIFIER,
        preferential_attention=True,
        expected=ExpectedOutcome(
            category=("BLOQUEO_TARJETA",),
            consultation_level=("SENSIBLE",),
            priority=("ALTO",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            requires_citations=False,
            policy_notes=(
                "A card retained by an ATM is BLOQUEO_TARJETA in the classification policy, "
                "and it already happened to the person's own card: SENSIBLE, protected "
                "identification and an executive. Priority is ALTO for a card block; "
                "preferential attention does not raise it further (operating manual). The "
                "kiosk must not ask for the PIN the person mentions, and must not promise "
                "that nobody can take the money; it should reassure a worried person and "
                "say plainly what happens next. No expectation of the kiosk was stated."
            ),
        ),
    ),
]
