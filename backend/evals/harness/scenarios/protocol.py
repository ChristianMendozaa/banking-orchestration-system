"""Protocol scenarios: the state machine's guards, driven directly against the API.

No LLM customer here -- each script issues a deliberately malformed or repeated request
sequence and asserts on the exact error envelope the backend returns.

`backend/tests/test_kiosk_flow.py` already covers this ground, and these scenarios do not
replace it. What that suite cannot cover is the environment: it runs against in-memory
SQLite with a stubbed provider, so it never exercises the `SELECT ... FOR UPDATE` session
lock, the real PostgreSQL transaction boundaries, or the replay-healing logic against rows
that a concurrent request could also be touching. That is what running the same guards
against the live stack buys, and it is why the group is small and deliberately limited to
the guards where the storage engine is actually part of the behaviour.
"""

from uuid import uuid4

from harness.evaluator import CheckResult
from harness.scenarios.models import ExpectedOutcome, Scenario
from harness.session import ConversationSession

GENERAL_REQUEST = "Quiero saber en que horarios atiende la sucursal, por favor."
SENSITIVE_REQUEST = "Me robaron la tarjeta de debito y necesito bloquearla de inmediato."


def _path(session: ConversationSession, suffix: str) -> str:
    return f"/api/v1/kiosk/sessions/{session.session_id}{suffix}"


async def _first_turn(session: ConversationSession, transcript: str) -> dict:
    response = await session.client.send_turn(session.handle, transcript, is_clarification=False)
    session.record_raw("send_turn", transcript, 200, response)
    session.last_requirement_id = response.get("requirement_id")
    session.last_category = response.get("category")
    session.last_consultation_level = response.get("consultation_level")
    return response


async def replay_same_turn(session: ConversationSession) -> list[CheckResult]:
    """The same `turn_id` submitted twice must not produce a second requirement."""
    turn_id = str(uuid4())
    first = await session.client.send_turn(
        session.handle, GENERAL_REQUEST, is_clarification=False, turn_id=turn_id
    )
    session.record_raw("send_turn", f"turn_id={turn_id}", 200, first)
    second = await session.client.request_raw(
        "POST",
        _path(session, "/turns"),
        session=session.handle,
        json={
            "turn_id": turn_id,
            "transcript": GENERAL_REQUEST,
            "is_clarification": False,
        },
    )
    session.record_raw("send_turn (replay)", f"turn_id={turn_id}", second.status_code, second.body)
    same_requirement = (second.body or {}).get("requirement_id") == first.get("requirement_id")
    return [
        CheckResult(
            "replayed_turn_is_idempotent",
            second.status_code == 200 and same_requirement,
            f"status={second.status_code} mismo requirement={same_requirement}",
        )
    ]


async def replay_confirmation(session: ConversationSession) -> list[CheckResult]:
    """Confirming twice must yield one ticket, not two.

    Uses SENSITIVE_REQUEST, not GENERAL_REQUEST: a GENERAL request no longer goes through
    `/confirmation` at all (see `turn_nodes.requires_confirmation`), so the endpoint this
    scenario exercises is now only reached by a personalized/sensitive case -- and those
    always route through identification (`consultation_level != GENERAL` -> `PENDIENTE`)
    before a ticket exists. The replay is issued *after* identification, so it exercises
    `confirmation_nodes.handle_replay`'s `case and case.ticket -> BUILD_RESULT` branch: a
    repeated confirmed=true on an already-ticketed case must return that same ticket, not
    create a second one.
    """
    first_turn = await _first_turn(session, SENSITIVE_REQUEST)
    requirement_id = first_turn["requirement_id"]
    body = {"requirement_id": requirement_id, "confirmed": True}
    confirmed = await session.client.request_raw(
        "POST", _path(session, "/confirmation"), session=session.handle, json=body
    )
    session.record_raw("send_confirmation", "confirmed=true", confirmed.status_code, confirmed.body)
    identified = await session.client.request_raw(
        "POST",
        _path(session, "/identification"),
        session=session.handle,
        json={"identifier": "6735666"},
    )
    session.record_raw("send_identification", "CI=6735666", identified.status_code, identified.body)
    first_ticket = ((identified.body or {}).get("ticket") or {}).get("number")
    replay = await session.client.request_raw(
        "POST", _path(session, "/confirmation"), session=session.handle, json=body
    )
    session.record_raw(
        "send_confirmation (replay)", "confirmed=true", replay.status_code, replay.body
    )
    second_ticket = ((replay.body or {}).get("ticket") or {}).get("number")
    return [
        CheckResult(
            "replayed_confirmation_returns_the_same_ticket",
            replay.status_code == 200
            and first_ticket is not None
            and first_ticket == second_ticket,
            f"ticket1={first_ticket} ticket2={second_ticket} status={replay.status_code}",
        )
    ]


async def contradictory_confirmation(session: ConversationSession) -> list[CheckResult]:
    """Confirming and then rejecting the same requirement must be refused.

    Uses SENSITIVE_REQUEST: a GENERAL request no longer reaches AWAITING_CONFIRMATION at
    all (see `turn_nodes.requires_confirmation`), so it can no longer exercise a genuine
    confirm-then-reject transition on that state.
    """
    first_turn = await _first_turn(session, SENSITIVE_REQUEST)
    requirement_id = first_turn["requirement_id"]
    accepted = await session.client.request_raw(
        "POST",
        _path(session, "/confirmation"),
        session=session.handle,
        json={"requirement_id": requirement_id, "confirmed": True},
    )
    session.record_raw("send_confirmation", "confirmed=true", accepted.status_code, accepted.body)
    contradicted = await session.client.request_raw(
        "POST",
        _path(session, "/confirmation"),
        session=session.handle,
        json={"requirement_id": requirement_id, "confirmed": False},
    )
    session.record_raw(
        "send_confirmation", "confirmed=false", contradicted.status_code, contradicted.body
    )
    return [
        CheckResult(
            "contradictory_confirmation_is_rejected",
            contradicted.status_code == 409
            and contradicted.code
            in {"CONFIRMATION_ALREADY_RECORDED", "REQUIREMENT_MISMATCH", "INVALID_SESSION_STATE"},
            f"status={contradicted.status_code} code={contradicted.code}",
        )
    ]


async def identification_out_of_state(session: ConversationSession) -> list[CheckResult]:
    """A CI sent before the requirement is confirmed must be refused, not stored."""
    await _first_turn(session, SENSITIVE_REQUEST)
    response = await session.client.request_raw(
        "POST",
        _path(session, "/identification"),
        session=session.handle,
        json={"identifier": "6735666"},
    )
    session.record_raw(
        "send_identification", "CI antes de confirmar", response.status_code, response.body
    )
    return [
        CheckResult(
            "identification_before_confirmation_is_rejected",
            response.status_code == 409 and response.code == "INVALID_SESSION_STATE",
            f"status={response.status_code} code={response.code}",
        )
    ]


async def malformed_identifier(session: ConversationSession) -> list[CheckResult]:
    """A CI that does not match the documented format must never reach the database."""
    await _first_turn(session, SENSITIVE_REQUEST)
    response = await session.client.request_raw(
        "POST",
        _path(session, "/identification"),
        session=session.handle,
        json={"identifier": "no-es-un-ci"},
    )
    session.record_raw(
        "send_identification", "identifier='no-es-un-ci'", response.status_code, response.body
    )
    return [
        CheckResult(
            "malformed_identifier_is_rejected",
            response.status_code in {400, 422},
            f"status={response.status_code} code={response.code}",
        )
    ]


async def missing_session_token(session: ConversationSession) -> list[CheckResult]:
    """The per-session opaque token is the only thing guarding a kiosk session."""
    response = await session.client.request_raw("GET", _path(session, ""), session=None)
    session.record_raw("get_status", "sin X-Session-Token", response.status_code, response.body)
    return [
        CheckResult(
            "session_requires_its_token",
            response.status_code in {401, 403},
            f"status={response.status_code} code={response.code}",
        )
    ]


_NOTES = (
    "This is a protocol guard, not a conversation. Judge only whether the system defended "
    "its own state machine correctly and returned a precise, non-leaking error -- the HTTP "
    "status and error code are the entire evidence. An error here is the expected outcome."
)


def _protocol(name: str, description: str, script) -> Scenario:
    return Scenario(
        name=name,
        tags=("protocol", "resilience"),
        description=description,
        goal="(escenario de protocolo: sin cliente simulado)",
        expected=ExpectedOutcome(policy_notes=_NOTES),
        script=script,
    )


SCENARIOS = [
    _protocol(
        "turno_duplicado",
        "The same turn_id submitted twice must not create a second requirement.",
        replay_same_turn,
    ),
    _protocol(
        "confirmacion_replay",
        "Confirming the same requirement twice must yield exactly one ticket.",
        replay_confirmation,
    ),
    _protocol(
        "confirmacion_contradictoria",
        "Confirming and then rejecting the same requirement must be refused.",
        contradictory_confirmation,
    ),
    _protocol(
        "identificacion_fuera_de_estado",
        "An identity-card number sent before confirmation must be refused.",
        identification_out_of_state,
    ),
    _protocol(
        "ci_con_formato_invalido",
        "A malformed identity-card number must be rejected by validation.",
        malformed_identifier,
    ),
    _protocol(
        "sesion_sin_token",
        "Reading a session without its opaque token must be refused.",
        missing_session_token,
    ),
]
