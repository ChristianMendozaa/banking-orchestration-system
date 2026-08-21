"""The spoken kiosk, end to end, without audio hardware or OpenAI.

`KioskVoiceSession` is driven directly against a fake WebSocket and a fake recogniser so
the whole turn loop -- transcript, orchestration, speech, barge-in -- runs in the test's own
event loop against the same in-memory database every other backend test uses.

The fake recogniser transcribes each audio frame to the text the test encoded into it. That
keeps ordering explicit: the test decides exactly when a sentence is finished, which is what
the semantic VAD decides in production.
"""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from starlette.websockets import WebSocketDisconnect

import app.services.voice.session as voice_session
from app.api.kiosk_voice import origin_allowed, voice_channel
from app.core.errors import AppError
from app.domain.enums import SessionStatus
from app.services.voice.session import KioskVoiceSession
from tests.conftest import TestSession, settings_for_tests, test_orchestrator

SPEECH_FRAME = b"\x00\x01" * 32


_STOP = object()


class FakeUpstream:
    """A transcription session that hears whatever the test says it heard."""

    def __init__(self) -> None:
        self.events: asyncio.Queue = asyncio.Queue()
        self.appended: list[str] = []
        self.input_audio_buffer = self

    async def append(self, audio: str) -> None:
        import base64

        payload = base64.b64decode(audio)
        self.appended.append(payload.hex())
        if payload == SPEECH_FRAME:
            return
        text = payload.decode("utf-8", errors="ignore")
        item_id = uuid4().hex
        await self.events.put(
            _event("input_audio_buffer.speech_started"),
        )
        await self.events.put(
            _event(
                "conversation.item.input_audio_transcription.completed",
                item_id=item_id,
                transcript=text,
            )
        )

    def drop(self) -> None:
        """The upstream transcription session going away underneath a live conversation."""
        self.events.put_nowait(_STOP)

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.events.get()
        if event is _STOP:
            raise StopAsyncIteration
        return event


def _event(kind: str, **fields):
    from types import SimpleNamespace

    return SimpleNamespace(type=kind, **fields)


class FakeProvider:
    def __init__(self) -> None:
        self.upstream = FakeUpstream()
        self.spoken: list[str] = []
        self.speech_delay = 0.0

    def open_transcription_session(self, _identifier: str):
        upstream = self.upstream

        class Manager:
            async def __aenter__(self):
                return upstream

            async def __aexit__(self, *_):
                return None

        return Manager()

    async def stream_speech(self, text: str):
        self.spoken.append(text)
        for _ in range(3):
            if self.speech_delay:
                await asyncio.sleep(self.speech_delay)
            yield b"\x11\x22" * 16


class FakeWebSocket:
    """Just enough of Starlette's WebSocket for the session driver to talk to."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.audio: list[bytes] = []
        self.closed_code: int | None = None
        self.headers: dict[str, str] = {}

    async def receive(self) -> dict:
        return await self.inbox.get()

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def send_bytes(self, payload: bytes) -> None:
        self.audio.append(payload)

    async def accept(self) -> None:
        pass

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_code = code

    # -- test-side helpers ------------------------------------------------
    def say(self, text: str) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "bytes": text.encode("utf-8")})

    def send_event(self, payload: dict) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "text": json.dumps(payload)})

    def hang_up(self) -> None:
        self.inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})

    def frames(self, kind: str) -> list[dict]:
        return [frame for frame in self.sent if frame["type"] == kind]

    async def wait_for(self, kind: str, timeout: float = 5.0) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            found = self.frames(kind)
            if found:
                return found[-1]
            await asyncio.sleep(0.01)
        raise AssertionError(f"no {kind!r} frame arrived; got {[f['type'] for f in self.sent]}")


IDENTIFY_LINE = "Para continuar, escribe tu CI"


def _line_beginning(websocket: "FakeWebSocket", prefix: str) -> dict | None:
    """The `speech.begin` frame for one specific line.

    Counting frames instead is brittle: an interruption drops lines that are still queued,
    so one can be cancelled before it ever announces a beginning and the ordinal of
    everything after it shifts.
    """
    return next(
        (frame for frame in websocket.frames("speech.begin") if frame["text"].startswith(prefix)),
        None,
    )


async def wait_until(predicate, description: str, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {description}")


async def _kiosk_session(client: AsyncClient) -> tuple[UUID, str]:
    response = await client.post("/api/v1/kiosk/sessions", json={})
    assert response.status_code == 201, response.text
    data = response.json()
    return UUID(data["session_id"]), data["session_token"]


def _voice(websocket: FakeWebSocket, session_id: UUID, token: str, provider: FakeProvider):
    return KioskVoiceSession(
        websocket=websocket,
        session_id=session_id,
        token=token,
        orchestrator=test_orchestrator,
        provider=provider,
        settings=settings_for_tests,
        session_factory=TestSession,
    )


async def _run(session: KioskVoiceSession) -> asyncio.Task:
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0)
    return task


async def _stop(task: asyncio.Task, websocket: FakeWebSocket) -> None:
    websocket.hang_up()
    try:
        await asyncio.wait_for(task, timeout=5)
    except (TimeoutError, WebSocketDisconnect):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_spoken_general_question_is_answered_out_loud(client: AsyncClient) -> None:
    """The whole point of the change: audio in, the ordinary orchestrator, audio out.

    Nothing between the recogniser and `analyze_turn` is allowed to reword the sentence, so
    the transcript that reaches the classifier is the one the customer produced.
    """
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    task = await _run(_voice(websocket, session_id, token, provider))

    await websocket.wait_for("speech.end")
    assert provider.spoken[0].startswith("Hola, soy tu asistente virtual")

    websocket.say("Quiero conocer el horario de atencion de la sucursal")
    result = await websocket.wait_for("turn.result")

    assert result["payload"]["resolution_type"] == "AUTOMATIC"
    spoken_answer = result["payload"]["speech_text"]
    await wait_until(lambda: spoken_answer in provider.spoken, "the answer to be spoken")
    assert websocket.audio, "the answer was never streamed as audio"
    await _stop(task, websocket)


async def test_the_classified_transcript_is_the_one_that_was_said(
    client: AsyncClient,
) -> None:
    """The regression this whole change exists to make impossible.

    A live session once classified "Quiero portar el juego de mi tarjeta de debito" for
    someone who said "reportar el robo", because a model retyped the sentence between the
    recogniser and the classifier. There is no such model any more, so the two cannot
    diverge -- and the requirement stored for the turn proves it.
    """
    from sqlalchemy import select

    from app.db.models import Requirement

    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    task = await _run(_voice(websocket, session_id, token, provider))
    await websocket.wait_for("speech.end")

    spoken = "Quiero reportar el robo de mi tarjeta de debito"
    websocket.say(spoken)
    await websocket.wait_for("turn.analysis")

    async with TestSession() as db:
        requirement = await db.scalar(
            select(Requirement).where(Requirement.session_id == session_id)
        )
    assert requirement is not None
    assert "robo" in requirement.masked_text.lower()
    assert "juego" not in requirement.masked_text.lower()
    await _stop(task, websocket)


async def test_a_second_question_is_still_heard_after_an_automatic_answer(
    client: AsyncClient,
) -> None:
    """An answer the kiosk produced by itself does not end the conversation.

    The customer is still standing there, and the backend opens a separate case for a
    follow-up. Treating RESOLVED_AUTOMATIC as a closed microphone made the second question
    silently unhearable -- the kiosk looked like it was listening and was not.
    """
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    task = await _run(_voice(websocket, session_id, token, provider))
    await websocket.wait_for("speech.end")

    websocket.say("Quiero conocer el horario de atencion de la sucursal")
    first = await websocket.wait_for("turn.result")
    assert first["payload"]["resolution_type"] == "AUTOMATIC"

    websocket.say("Y que documentos piden para sacar un credito de consumo")
    await wait_until(
        lambda: len(websocket.frames("transcript.completed")) == 2,
        "the follow-up question to be heard",
    )
    assert provider.upstream.appended, "the microphone was closed after an automatic answer"
    await _stop(task, websocket)


async def test_barge_in_stops_the_kiosk_mid_sentence(client: AsyncClient, monkeypatch) -> None:
    """Talking over the kiosk is taking the turn, so the line is abandoned, not finished."""
    # Past the echo grace period below, which is not what this test is about.
    monkeypatch.setattr(voice_session, "BARGE_IN_GRACE_SECONDS", 0.0)

    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    provider.speech_delay = 0.2
    task = await _run(_voice(websocket, session_id, token, provider))

    await websocket.wait_for("speech.begin")
    await provider.upstream.events.put(_event("input_audio_buffer.speech_started"))

    cancelled = await websocket.wait_for("speech.cancel")
    assert cancelled["speech_id"] == websocket.frames("speech.begin")[0]["speech_id"]
    assert not websocket.frames("speech.end"), "the interrupted line reported as completed"
    await _stop(task, websocket)


async def test_the_kiosk_does_not_interrupt_itself_on_its_own_first_words(
    client: AsyncClient,
) -> None:
    """The opening moments of a line are the kiosk's own voice coming back, not a customer.

    The microphone stays open while the kiosk speaks, so the speakers leak into it, and the
    browser's echo canceller needs some of the line before it converges. Acting on a speech
    start that arrives in that window cancels the sentence the customer is waiting for --
    repeatedly, which is what turned a spoken answer into a stutter.
    """
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    provider.speech_delay = 0.2
    task = await _run(_voice(websocket, session_id, token, provider))

    await websocket.wait_for("speech.begin")
    await provider.upstream.events.put(_event("input_audio_buffer.speech_started"))

    await websocket.wait_for("speech.end")
    assert not websocket.frames("speech.cancel"), "the kiosk cut its own opening words"
    await _stop(task, websocket)


async def test_an_upstream_that_drops_is_a_failure_not_a_finished_visit(
    client: AsyncClient,
) -> None:
    """The transcription session going away must not read as the customer leaving.

    `_drive_turns` and `_speaker` loop forever and `_pump_client` exits only on a real
    disconnect, so this iterator running dry was once the single way `run` could return with
    no exception at all: nothing to re-raise, nothing logged, and a socket that closed 1000 --
    which the browser renders as "Atención finalizada" in the middle of a conversation.
    """
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    task = await _run(_voice(websocket, session_id, token, provider))
    await websocket.wait_for("speech.end")

    provider.upstream.drop()

    with pytest.raises(voice_session.UpstreamClosed):
        await asyncio.wait_for(task, timeout=5)
    assert not websocket.frames("session.finished"), "a dropped upstream reported a clean end"


async def test_an_ambiguous_confirmation_is_re_asked_rather_than_guessed(
    client: AsyncClient,
) -> None:
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    task = await _run(_voice(websocket, session_id, token, provider))
    await websocket.wait_for("speech.end")

    websocket.say("Quiero denunciar un fraude en mi cuenta")
    analysis = await websocket.wait_for("turn.analysis")
    assert analysis["payload"]["next_action"] == "CONFIRM"

    websocket.say("mmm, tal vez, quizas")
    await asyncio.sleep(0.2)
    assert "Por favor, respóndeme claramente" in provider.spoken[-1]
    assert not websocket.frames("turn.result"), "an unclear answer opened a case"
    await _stop(task, websocket)


async def test_a_spoken_yes_advances_the_flow(client: AsyncClient) -> None:
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    task = await _run(_voice(websocket, session_id, token, provider))
    await websocket.wait_for("speech.end")

    websocket.say("Quiero denunciar un fraude en mi cuenta")
    await websocket.wait_for("turn.analysis")

    websocket.say("si, asi es")
    result = await websocket.wait_for("turn.result")
    assert result["payload"]["next_action"] == "IDENTIFY"
    # The CI is typed into a protected field, so the microphone closes rather than inviting
    # anyone to read an identity document out loud in a branch. It closes after the line has
    # been spoken, so poll for it instead of reading whatever state happens to be current.
    await wait_until(
        lambda: any(frame["value"] == "muted" for frame in websocket.frames("session.state")),
        "the microphone to close for identification",
    )
    await _stop(task, websocket)


async def test_audio_is_ignored_once_the_flow_closed_the_microphone(
    client: AsyncClient,
) -> None:
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    session = _voice(websocket, session_id, token, provider)
    task = await _run(session)
    await websocket.wait_for("speech.end")

    session._status = SessionStatus.AWAITING_IDENTIFICATION
    websocket.say("mi carnet es 6735666")
    await asyncio.sleep(0.1)
    assert provider.upstream.appended == [], "audio was relayed while the mic was closed"
    await _stop(task, websocket)


async def test_a_ci_typed_mid_sentence_still_gets_its_ticket_spoken(
    client: AsyncClient,
) -> None:
    """The reported bug, end to end.

    Someone who reads the CI card and types their number before the kiosk has finished
    explaining it used to hear nothing at all afterwards: the identification line was still
    streaming, the ticket line queued behind it, and the single mutable task slot the two
    shared meant an interruption cancelled the wrong one -- announcing the id of the line
    that was playing while killing the line that had not started.
    """
    session_id, token = await _kiosk_session(client)
    headers = {"X-Session-Token": token}
    websocket, provider = FakeWebSocket(), FakeProvider()
    provider.speech_delay = 0.2
    task = await _run(_voice(websocket, session_id, token, provider))
    await websocket.wait_for("speech.end")

    websocket.say("Quiero denunciar un fraude en mi cuenta")
    await websocket.wait_for("turn.analysis")
    websocket.say("si, asi es")
    await websocket.wait_for("turn.result")

    # The line still streaming while the customer reads the card and types. Named rather
    # than taken from `wait_for`, which returns whichever line happens to be current.
    await wait_until(
        lambda: _line_beginning(websocket, IDENTIFY_LINE) is not None,
        "the identification line to start",
        timeout=10.0,
    )
    identify_line = _line_beginning(websocket, IDENTIFY_LINE)
    assert identify_line is not None

    identification = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        json={"identifier": "6735666"},
        headers=headers,
    )
    assert identification.status_code == 200, identification.text

    # A cancellation may already have happened for good reason -- saying "si, asi es" over
    # the confirmation question is ordinary barge-in -- so only what follows the resync is
    # what this test is about.
    before = len(websocket.frames("speech.cancel"))

    # Exactly what the browser sends the moment the CI is submitted.
    websocket.send_event({"type": "client.resync"})

    await wait_until(
        lambda: any("Tu ticket es" in line for line in provider.spoken),
        "the ticket to be spoken after identification",
        # The longest serial chain in this file: a confirmation turn, an HTTP
        # identification, a resync and two delayed speech lines.
        timeout=15.0,
    )
    cancelled = websocket.frames("speech.cancel")[before:]
    assert cancelled, "the explanation kept playing over someone who had already answered"
    # One line was dropped, and it is the one that was named. Announcing the wrong id made
    # the browser discard the ticket audio it had just been handed.
    assert [frame["speech_id"] for frame in cancelled] == [identify_line["speech_id"]]
    await _stop(task, websocket)


async def test_a_stray_speech_start_never_cancels_a_line_the_mic_could_not_hear(
    client: AsyncClient,
) -> None:
    """Audio appended before the flow closed the microphone can surface as a speech start
    seconds later. Treating that as barge-in cancelled the line the customer was waiting
    for -- and nobody had said anything."""
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    provider.speech_delay = 0.2
    session = _voice(websocket, session_id, token, provider)
    task = await _run(session)
    await websocket.wait_for("speech.begin")

    session._status = SessionStatus.AWAITING_IDENTIFICATION
    await provider.upstream.events.put(_event("input_audio_buffer.speech_started"))

    await websocket.wait_for("speech.end")
    assert not websocket.frames("speech.cancel"), "a closed microphone interrupted the kiosk"
    await _stop(task, websocket)


async def test_a_line_cut_short_is_not_remembered_as_said(client: AsyncClient) -> None:
    """`_spoken_transitions` is how the kiosk avoids repeating itself across a resync.

    Recording a transition before speaking it meant an interrupted line counted as
    delivered, so the resync that follows identification returned at that check and the
    ticket was never announced at all.
    """
    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    provider.speech_delay = 0.2
    session = _voice(websocket, session_id, token, provider)
    task = await _run(session)
    await websocket.wait_for("speech.end")

    websocket.say("Quiero denunciar un fraude en mi cuenta")
    await websocket.wait_for("turn.analysis")
    websocket.say("si, asi es")
    await websocket.wait_for("turn.result")
    # The identification line, still streaming when the customer starts typing.
    await wait_until(
        lambda: _line_beginning(websocket, IDENTIFY_LINE) is not None,
        "the identification line to start",
        timeout=10.0,
    )
    identify_line = _line_beginning(websocket, IDENTIFY_LINE)
    assert identify_line is not None

    await session._cancel_speech()

    await wait_until(
        lambda: session._spoken_transitions == set(),
        "the interrupted line to stay unrecorded",
    )
    assert websocket.frames("speech.cancel")[-1]["speech_id"] == identify_line["speech_id"]
    await _stop(task, websocket)


async def test_a_slow_turn_is_covered_by_the_screen_not_by_speech(
    client: AsyncClient, monkeypatch
) -> None:
    """Nothing is spoken between the customer's sentence and the answer to it.

    A holding line ("Un momento, estoy revisando eso.") used to cover turns longer than two
    seconds. It was removed because it made the wait it covered longer: the answer could not
    be spoken until the holding line had finished streaming, so a turn that was already
    arriving paid for a second round trip to the speech model. The `thinking` state on screen
    is the affordance now, and it costs no audio.
    """
    original = test_orchestrator.analyze_turn

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.3)
        return await original(*args, **kwargs)

    monkeypatch.setattr(test_orchestrator, "analyze_turn", slow)

    session_id, token = await _kiosk_session(client)
    websocket, provider = FakeWebSocket(), FakeProvider()
    task = await _run(_voice(websocket, session_id, token, provider))
    await websocket.wait_for("speech.end")
    spoken_before = len(provider.spoken)

    websocket.say("Quiero conocer el horario de atencion de la sucursal")
    result = await websocket.wait_for("turn.result")
    answer = result["payload"]["speech_text"]
    await wait_until(lambda: answer in provider.spoken, "the answer to be spoken")

    # The answer, and nothing in front of it.
    assert provider.spoken[spoken_before:] == [answer]
    await _stop(task, websocket)


# ----------------------------------------------------------------- handshake guards


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("http://test", True),
        ("http://evil.test", False),
        ("https://test", False),
        (None, True),
    ],
)
def test_origin_is_checked_because_cors_middleware_does_not_apply(
    origin: str | None, allowed: bool
) -> None:
    assert origin_allowed(origin, settings_for_tests) is allowed


async def test_a_bad_token_never_gets_an_open_socket(client: AsyncClient) -> None:
    session_id, _ = await _kiosk_session(client)
    websocket = FakeWebSocket()

    await voice_channel(
        websocket=websocket,
        session_id=session_id,
        token="not-the-token",
        settings=settings_for_tests,
        orchestrator=test_orchestrator,
        provider=FakeProvider(),
        session_factory=TestSession,
    )
    assert websocket.closed_code == 1008
    assert websocket.sent == []


async def test_voice_is_refused_when_openai_is_not_configured() -> None:
    websocket = FakeWebSocket()
    await voice_channel(
        websocket=websocket,
        session_id=uuid4(),
        token="irrelevant",
        settings=settings_for_tests,
        orchestrator=test_orchestrator,
        provider=None,
        session_factory=TestSession,
    )
    assert websocket.closed_code == 1008


def test_app_error_from_auth_is_not_leaked_as_a_message() -> None:
    error = AppError("SESSION_EXPIRED", "La sesion de kiosco ha vencido", 401)
    assert error.code == "SESSION_EXPIRED"
