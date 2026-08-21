"""Drive one spoken kiosk conversation: transcribe, orchestrate, speak.

The kiosk used to run OpenAI's speech-to-speech model in the browser and then spend most of
its code stopping that model from doing anything. Every sentence the customer heard was
authored by the orchestrator and forced through the model verbatim; every transcript the
model typed was thrown away in favour of the session's own transcription. What is left once
that model is removed is this file: audio in, the same orchestrator graph the text kiosk and
the eval harness already use, audio out.

The customer's words reach `analyze_turn` as the recogniser produced them, so there is only
one transcript in the system and nothing left to reconcile.
"""

import asyncio
import base64
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.api.deps import resolve_kiosk_session
from app.core.config import Settings
from app.db.models import KioskSession
from app.domain.enums import SessionStatus
from app.domain.schemas import (
    ConfirmationRequest,
    FlowResult,
    TurnAnalysisResponse,
    TurnRequest,
)
from app.services.openai_provider import OpenAIProvider
from app.services.orchestrator import OrchestratorService
from app.services.voice.confirmation import explicit_confirmation
from app.services.voice.transcripts import IncomingMessage, record_messages

logger = logging.getLogger(__name__)

WELCOME_TEXT = "Hola, soy tu asistente virtual. ¿En qué puedo ayudarte hoy?"
REASK_CONFIRMATION_TEXT = "Por favor, respóndeme claramente sí para confirmar o no para corregir."
ERROR_TEXT = "No pude procesar tu solicitud en este momento. Inténtalo nuevamente."

# How much of a spoken line is protected from barge-in. The microphone is open while the
# kiosk talks, so the first fraction of every line reaches the recogniser through the
# speakers before the browser's echo canceller has adapted to it. Long enough to cover that;
# short enough that a customer who really does talk over the opening words is still heard on
# their next breath.
BARGE_IN_GRACE_SECONDS = 0.4

# Statuses in which the microphone is closed. AWAITING_IDENTIFICATION is the important one:
# the CI is typed into a protected field on screen and must never be dictated aloud. The
# rest are the ends of the conversation -- a case now owned by an executive, a declined
# request, a failure.
#
# RESOLVED_AUTOMATIC is deliberately absent. A question the kiosk answered by itself does
# not end the session: the customer is still standing there and may well have a second
# question, and the backend opens a separate case for it. Closing the microphone there
# means the follow-up is never heard.
MUTED_STATUSES = {
    SessionStatus.AWAITING_IDENTIFICATION,
    SessionStatus.ASSIGNED,
    SessionStatus.DECLINED,
    SessionStatus.FAILED,
}


class UpstreamClosed(RuntimeError):
    """The transcription session ended while the customer was still being served."""


def is_terminal(result: FlowResult) -> bool:
    """Whether this result ends the session.

    An automatic answer deliberately does not: the customer is still standing there and may
    have a second question, and the backend allows more than one case per session.
    """
    return result.next_action == "COMPLETE" and result.resolution_type != "AUTOMATIC"


@dataclass
class _Line:
    """One sentence on its way to the speaker.

    The id travels with the text. It used to live in a single `_active_speech_id` field
    shared by every line, so an interruption arriving while one line was streaming and
    another was queued behind it announced the cancellation of whichever id happened to be
    in the field -- cancelling one sentence in the browser and silencing the other.
    """

    speech_id: str
    text: str
    cancelled: bool = False
    spoken: asyncio.Event = field(default_factory=asyncio.Event)


class KioskVoiceSession:
    def __init__(
        self,
        websocket: WebSocket,
        session_id: UUID,
        token: str,
        orchestrator: OrchestratorService,
        provider: OpenAIProvider,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.websocket = websocket
        self.session_id = session_id
        self.token = token
        self.orchestrator = orchestrator
        self.provider = provider
        self.settings = settings
        self.session_factory = session_factory

        self._transcripts: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._speech: asyncio.Queue[_Line] = asyncio.Queue()
        self._streaming: tuple[_Line, asyncio.Task[None]] | None = None
        self._spoken_transitions: set[str] = set()
        self._status = SessionStatus.CREATED
        self._requirement_id: UUID | None = None
        self._is_clarification = False
        self._closing = False
        self._upstream: Any = None
        self._speaking_since: float | None = None

    # ---------------------------------------------------------------- lifecycle

    async def run(self) -> None:
        async with self.provider.open_transcription_session(str(self.session_id)) as upstream:
            self._upstream = upstream
            await self._refresh_status()
            await self._set_state("listening")
            self._enqueue(WELCOME_TEXT)

            tasks = [
                asyncio.create_task(self._pump_client(), name="voice-client"),
                asyncio.create_task(self._pump_upstream(), name="voice-upstream"),
                asyncio.create_task(self._drive_turns(), name="voice-turns"),
                asyncio.create_task(self._speaker(), name="voice-speech"),
            ]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                # Surface a genuine failure rather than closing as if the customer left.
                for task in done:
                    exc = task.exception()
                    if exc is not None and not isinstance(exc, WebSocketDisconnect):
                        raise exc
            finally:
                self._closing = True
                await self._cancel_speech()

    # ------------------------------------------------------------- browser side

    async def _pump_client(self) -> None:
        """Relay microphone audio upstream and handle the browser's control frames."""
        while True:
            message = await self.websocket.receive()
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))

            chunk = message.get("bytes")
            if chunk:
                # Audio keeps flowing while the kiosk is speaking -- that is what makes
                # barge-in possible. It stops only when the flow itself closed the mic.
                if self._status not in MUTED_STATUSES:
                    await self._upstream.input_audio_buffer.append(
                        audio=_b64(chunk),
                    )
                continue

            text = message.get("text")
            if text:
                await self._handle_client_event(json.loads(text))

    async def _handle_client_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "client.resync":
            # Sent after identification, which happens over HTTP because the CI is typed
            # rather than spoken. The socket has no other way to learn the flow moved on.
            await self._refresh_status(speak=True)
        elif kind == "client.barge_in":
            await self._cancel_speech()

    # ------------------------------------------------------------ upstream side

    async def _pump_upstream(self) -> None:
        """Consume transcription events from OpenAI.

        Returning is not an ending. `_drive_turns` and `_speaker` loop forever and
        `_pump_client` exits only when the customer disconnects, so this iterator running dry
        -- the upstream transcription session dropping -- used to be the one way `run` could
        return with no exception at all: `asyncio.wait` found nothing to re-raise, the
        endpoint fell through, and the browser was told the visit was over by a socket that
        closed 1000 with nothing in the log. It raises now, so the close carries 1011 and the
        reason says which half failed.
        """
        async for event in self._upstream:
            kind = getattr(event, "type", None)
            if kind == "input_audio_buffer.speech_started":
                # Barge-in. The customer talking over the kiosk is the customer taking the
                # turn, so the kiosk stops mid-sentence rather than finishing its line.
                #
                # Not while the microphone is closed, though. Audio appended upstream before
                # the flow muted it can surface as a speech start seconds later, and acting
                # on it there cancelled the line the customer was actually waiting for --
                # the ticket, spoken just after they typed their CI.
                #
                # Nor in the first moments of a line. The microphone stays open while the
                # kiosk speaks -- that is what makes barge-in possible -- so the speakers
                # leak into it, and browser echo cancellation needs a little of the line
                # before it converges. A speech start inside that window is the kiosk hearing
                # itself far more often than it is a customer interrupting, and acting on it
                # chops the sentence into the stutter this grace period exists to stop.
                if self._status not in MUTED_STATUSES and not self._line_is_settling():
                    await self._cancel_speech()
                    await self._set_state("listening")
            elif kind == "conversation.item.input_audio_transcription.delta":
                await self._send(
                    {
                        "type": "transcript.delta",
                        "item_id": getattr(event, "item_id", ""),
                        "text": getattr(event, "delta", "") or "",
                    }
                )
            elif kind == "conversation.item.input_audio_transcription.completed":
                transcript = (getattr(event, "transcript", "") or "").strip()
                item_id = getattr(event, "item_id", "") or uuid4().hex
                if transcript:
                    await self._send(
                        {
                            "type": "transcript.completed",
                            "item_id": item_id,
                            "text": transcript,
                        }
                    )
                    await self._transcripts.put((item_id, transcript))
            elif kind == "conversation.item.input_audio_transcription.failed":
                logger.warning("kiosk voice transcription failed: %s", event)
            elif kind == "error":
                logger.error("kiosk voice upstream error: %s", event)
        raise UpstreamClosed("the transcription session ended")

    # ----------------------------------------------------------------- the turn

    async def _drive_turns(self) -> None:
        """One turn at a time. A second sentence waits for the first to be answered."""
        while True:
            item_id, transcript = await self._transcripts.get()
            try:
                await self._handle_transcript(item_id, transcript)
            except Exception:
                logger.exception("kiosk voice turn failed")
                await self._send({"type": "error", "code": "TURN_FAILED", "message": ERROR_TEXT})
                await self._say_now(ERROR_TEXT, supersede=True)

    async def _handle_transcript(self, item_id: str, transcript: str) -> None:
        """Answer one customer turn.

        Nothing is spoken between the transcript landing and the answer. A holding line used
        to cover turns longer than two seconds, but the kiosk now classifies and grounds fast
        enough that it mostly arrived as a second TTS round trip in front of an answer that
        was already coming -- and because the answer could not be spoken until the holding
        line had finished streaming, it made the wait it was covering for longer. The
        `thinking` state on screen is the affordance now, and it costs no audio.
        """
        if self._status in MUTED_STATUSES:
            return
        await self._record(item_id, "CUSTOMER", transcript)
        await self._set_state("thinking")

        if self._status == SessionStatus.AWAITING_CONFIRMATION and self._requirement_id is not None:
            confirmed = explicit_confirmation(transcript)
            if confirmed is None:
                await self._say_now(REASK_CONFIRMATION_TEXT)
                return
            await self._apply_flow(await self._confirm(confirmed))
            return
        await self._apply_analysis(await self._analyze(transcript))

    async def _analyze(self, transcript: str) -> TurnAnalysisResponse:
        async with self.session_factory() as db:
            kiosk_session = await self._load(db)
            response = await self.orchestrator.analyze_turn(
                db,
                kiosk_session,
                TurnRequest(
                    turn_id=uuid4(),
                    transcript=transcript,
                    is_clarification=self._is_clarification,
                ),
            )
            await db.commit()
            return response

    async def _confirm(self, confirmed: bool) -> FlowResult:
        async with self.session_factory() as db:
            kiosk_session = await self._load(db)
            result = await self.orchestrator.confirm(
                db,
                kiosk_session,
                ConfirmationRequest(requirement_id=self._requirement_id, confirmed=confirmed),
            )
            await db.commit()
            return result

    async def _apply_analysis(self, analysis: TurnAnalysisResponse) -> None:
        self._requirement_id = analysis.requirement_id
        self._status = analysis.status
        self._is_clarification = analysis.next_action == "CLARIFY"

        # A confident GENERAL request resolves on this same turn and arrives with the whole
        # answer embedded, so it is a completed flow rather than an analysis awaiting one.
        if analysis.next_action == "COMPLETE" and analysis.result is not None:
            await self._apply_flow(analysis.result)
            return

        await self._send({"type": "turn.analysis", "payload": _dump(analysis)})
        await self._record(f"assistant-{uuid4().hex}", "ASSISTANT", analysis.speech_text)
        await self._say_now(analysis.speech_text)
        if analysis.next_action == "DECLINE":
            await self._finish()
        else:
            await self._set_state("listening")

    async def _apply_flow(self, result: FlowResult, supersede: bool = False) -> None:
        key = _transition_key(result)
        self._requirement_id = result.requirement_id
        self._status = result.status
        self._is_clarification = False

        await self._send({"type": "turn.result", "payload": _dump(result)})
        if key in self._spoken_transitions:
            return
        await self._record(f"assistant-{uuid4().hex}", "ASSISTANT", result.speech_text)
        # Remembered only once it has actually been said. Marking it beforehand meant a line
        # cut short by an interruption counted as spoken, so the resync that follows
        # identification returned at the check above and the ticket was never announced.
        if await self._say_now(result.speech_text, supersede=supersede):
            self._spoken_transitions.add(key)

        if is_terminal(result):
            await self._finish()
        elif result.next_action == "IDENTIFY":
            await self._set_state("muted")
        else:
            await self._set_state("listening")

    async def _finish(self) -> None:
        await self._send({"type": "session.finished"})
        self._closing = True
        with contextlib.suppress(RuntimeError):
            await self.websocket.close(code=1000)

    # ------------------------------------------------------------------ speech

    def _enqueue(self, text: str) -> _Line | None:
        """Put one line in line for the speaker. Nothing is spoken from the caller's task."""
        if self._closing or not text:
            return None
        line = _Line(speech_id=uuid4().hex, text=text)
        self._speech.put_nowait(line)
        return line

    async def _say_now(self, text: str, supersede: bool = False) -> bool:
        """Speak one line and wait for it. False if it was cut short and went unheard.

        `supersede` is for a line that replaces what is being said rather than following it:
        the customer typed their CI while the kiosk was still explaining the field, so the
        explanation is now noise and the ticket is what they are waiting for. The ordinary
        case is False -- a holding line already half-spoken is allowed to finish, because
        cutting it mid-word sounds worse than the second it costs.
        """
        if supersede:
            await self._cancel_speech()
        line = self._enqueue(text)
        if line is None:
            return False
        await line.spoken.wait()
        return not line.cancelled

    async def _speaker(self) -> None:
        """One line at a time, in order.

        Each line streams in its own task so that an interruption can cancel the sentence
        without taking this loop down with it.
        """
        while True:
            line = await self._speech.get()
            if line.cancelled or self._closing:
                line.spoken.set()
                continue
            task = asyncio.create_task(self._stream(line), name="voice-line")
            self._streaming = (line, task)
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # `_cancel_speech` leaves the task finished; anything else is this loop
                # itself being torn down, and the line it was streaming goes with it.
                if not task.done():
                    task.cancel()
                    raise
            except Exception:
                logger.exception("kiosk voice speech failed")
            finally:
                if self._streaming is not None and self._streaming[1] is task:
                    self._streaming = None
                line.spoken.set()

    async def _stream(self, line: _Line) -> None:
        """Stream one line as PCM16, framed so the browser knows where it starts and ends."""
        if self._closing:
            return
        await self._send({"type": "speech.begin", "speech_id": line.speech_id, "text": line.text})
        await self._set_state("speaking")
        self._speaking_since = time.monotonic()
        try:
            async for chunk in self.provider.stream_speech(line.text):
                await self.websocket.send_bytes(chunk)
            await self._send({"type": "speech.end", "speech_id": line.speech_id})
        finally:
            self._speaking_since = None

    def _line_is_settling(self) -> bool:
        """Whether a line has only just started, and a speech start is probably its echo."""
        started = self._speaking_since
        return started is not None and time.monotonic() - started < BARGE_IN_GRACE_SECONDS

    async def _cancel_speech(self) -> None:
        """Stop what is being said and drop everything queued behind it.

        Both halves matter. Cancelling only the streaming line leaves a queued one to start
        playing over the customer who just interrupted; dropping only the queue leaves the
        current sentence running. Each dropped line announces its own id, so the browser
        discards that line's audio and nothing else.
        """
        dropped: list[_Line] = []
        current, self._streaming = self._streaming, None
        if current is not None:
            line, task = current
            if not task.done():
                task.cancel()
                # gather rather than await: a speech task that failed on its way out should
                # not replace the interruption we are handling with its own exception.
                await asyncio.gather(task, return_exceptions=True)
            dropped.append(line)
        while not self._speech.empty():
            dropped.append(self._speech.get_nowait())
        for line in dropped:
            line.cancelled = True
            line.spoken.set()
            if not self._closing:
                # Sent from here rather than from the cancelled coroutine, which cannot do
                # I/O of its own.
                await self._send({"type": "speech.cancel", "speech_id": line.speech_id})

    # ------------------------------------------------------------------ plumbing

    async def _load(self, db: AsyncSession) -> KioskSession:
        return await resolve_kiosk_session(db, self.session_id, self.token)

    async def _refresh_status(self, speak: bool = False) -> None:
        """Re-read the flow from the database.

        Called on connect and whenever the browser reports that an out-of-band step
        finished -- identification is the only one, and it is out of band because the CI is
        typed rather than spoken.
        """
        async with self.session_factory() as db:
            kiosk_session = await self._load(db)
            snapshot = await self.orchestrator.build_session_status(db, kiosk_session)
        self._status = snapshot.status
        analysis = snapshot.analysis
        if analysis is not None:
            self._requirement_id = analysis.requirement_id
            self._is_clarification = analysis.next_action == "CLARIFY"
        if snapshot.result is not None and speak:
            # The step that just finished happened on screen, not out loud, so whatever the
            # kiosk was still saying about it is stale the moment it lands here.
            await self._apply_flow(snapshot.result, supersede=True)
        elif kiosk_session.status == SessionStatus.CREATED:
            await self._mark_listening()

    async def _mark_listening(self) -> None:
        async with self.session_factory() as db:
            kiosk_session = await self._load(db)
            if kiosk_session.status == SessionStatus.CREATED:
                kiosk_session.status = SessionStatus.LISTENING
                await db.commit()
        self._status = SessionStatus.LISTENING

    async def _record(self, item_id: str, role: str, text: str) -> None:
        async with self.session_factory() as db:
            kiosk_session = await self._load(db)
            await record_messages(
                db, kiosk_session, [IncomingMessage(item_id=item_id, role=role, text=text)]
            )
            await db.commit()

    async def _set_state(self, value: str) -> None:
        await self._send({"type": "session.state", "value": value})

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._closing and payload.get("type") != "session.finished":
            return
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await self.websocket.send_text(json.dumps(payload))


def _b64(chunk: bytes) -> str:
    return base64.b64encode(chunk).decode("ascii")


def _dump(model: TurnAnalysisResponse | FlowResult) -> dict[str, Any]:
    return json.loads(model.model_dump_json())


def _transition_key(result: FlowResult) -> str:
    if result.next_action == "COMPLETE" and result.ticket:
        return f"ticket:{result.ticket.id}"
    return f"{result.requirement_id}:{result.next_action}"
