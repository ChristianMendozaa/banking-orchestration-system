import type { FlowResult, KioskSession, TurnAnalysis } from "@/lib/types"

// Both directions of the channel run at this rate. The transcription session accepts only
// 24 kHz PCM and the speech model returns it, so matching the AudioContext to it means the
// browser never resamples and never decodes.
export const SAMPLE_RATE = 24_000

// The WebSocket "policy violation" code, which the backend uses for a refusal it made on
// purpose -- a disallowed origin, an unconfigured provider, a session that cannot be served.
const CLOSE_POLICY_VIOLATION = 1008
const WORKLET_URL = "/kiosk-audio-worklet.js"

// How long a card waits for its own sentence to start being spoken before it goes on screen
// anyway. Every business frame arrives just ahead of the speech it belongs to, and showing
// it early is what made the kiosk read as a screen with a voice bolted on rather than
// something talking. The cap exists because a line is not always spoken at all -- a repeated
// transition is deduplicated on the backend -- and a person must never be left looking at a
// stale card waiting for audio that is not coming.
const PRESENTATION_CAP_MS = 1_500

// Spanish text-to-speech runs at roughly this rate. Used only to pace the on-screen text
// while a line is still streaming in; once the last chunk has arrived the exact sample count
// is known and takes over. Without an estimate the caption would either sit blank until the
// stream finished or -- dividing by however much has arrived so far -- race ahead of the
// voice, which is the bug this pacing exists to fix.
const SPEECH_CHARS_PER_SECOND = 15

export type VoiceSessionState =
  | "listening"
  | "thinking"
  | "speaking"
  | "muted"

export interface VoiceCaption {
  id: string
  role: "user" | "assistant"
  text: string
  completed: boolean
}

export interface KioskVoiceHandlers {
  onState: (state: VoiceSessionState) => void
  onCaptions: (captions: VoiceCaption[]) => void
  onAnalysis: (analysis: TurnAnalysis) => void
  onResult: (result: FlowResult) => void
  /** The visit is over: the backend said so before closing. */
  onFinished: () => void
  /**
   * The socket closed without the backend ever saying the visit was over.
   *
   * A separate handler because the two are opposite outcomes that used to be one. Any close
   * -- an upstream transcription session dropping, a backend fault, a network blip -- was
   * reported as a finished visit, so a conversation in progress ended on "Atención
   * finalizada" with no error and no way back. `retryable` is false only for a close the
   * backend chose as a matter of policy, where reconnecting would be refused again.
   */
  onDropped: (retryable: boolean) => void
  onError: (message: string) => void
}

interface ServerFrame {
  type: string
  value?: string
  item_id?: string
  text?: string
  speech_id?: string
  message?: string
  payload?: unknown
}

interface PlayerMessage {
  type: "progress" | "ended" | "drained"
  speechId?: string
  playedSamples?: number
  queuedSamples?: number
  cancelled?: boolean
}

interface SpokenLine {
  seq: number
  text: string
  /** Every chunk has arrived, so the queued sample count is now the true total. */
  complete: boolean
  played: number
  queued: number
  /** Characters already on screen. Only ever moves forward. */
  revealed: number
}

export function voiceSocketUrl(session: KioskSession, base: string): string {
  const url = new URL(
    `/api/v1/kiosk/sessions/${session.session_id}/voice`,
    base.replace(/^http/, "ws"),
  )
  // A browser cannot set headers on a WebSocket handshake, so the session token travels as
  // a query parameter. It is the same opaque token the HTTP API takes in X-Session-Token
  // and the backend authenticates it with the same function.
  url.searchParams.set("token", session.session_token)
  return url.toString()
}

/**
 * The kiosk's spoken channel.
 *
 * Microphone audio goes up, transcripts, flow results and synthesised speech come down.
 * There is no model in this file and no OpenAI credential in this browser: the backend runs
 * the recogniser, the orchestrator and the speech synthesis, and this connection carries
 * audio to and from it.
 *
 * Speech arrives far faster than it plays, so nothing here treats a delivered byte as a
 * heard one. The player worklet reports what has actually reached the speaker, and that
 * report is what drives the on-screen text, the cards, the state the customer sees and --
 * through `drain` -- when the audio graph is allowed to be torn down.
 */
export class KioskVoiceConnection {
  private socket: WebSocket | null = null
  private context: AudioContext | null = null
  private stream: MediaStream | null = null
  private micNode: AudioWorkletNode | null = null
  private playerNode: AudioWorkletNode | null = null
  private captions: VoiceCaption[] = []
  private closed = false
  /** Whether the backend announced the end of the visit before the socket went away. */
  private finished = false

  private lines = new Map<string, SpokenLine>()
  private lineSeq = 0
  private currentSpeechId: string | null = null
  private playing = false
  private drainWaiters: (() => void)[] = []

  // Business frames held back until the sentence they belong to starts being spoken.
  private deferred: (() => void)[] = []
  private deferredAfterSeq = 0
  private deferredTimer: ReturnType<typeof setTimeout> | null = null

  // A server state that would contradict what is still coming out of the speaker.
  private pendingState: VoiceSessionState | null = null

  constructor(private readonly handlers: KioskVoiceHandlers) {}

  async connect(session: KioskSession, baseUrl: string): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Este navegador no permite capturar audio")
    }

    // Browser-side echo cancellation is what keeps the kiosk from transcribing its own
    // speakers. Without it, every sentence it says arrives back as a customer turn.
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    })

    const context = new AudioContext({ sampleRate: SAMPLE_RATE })
    this.context = context
    await context.audioWorklet.addModule(WORKLET_URL)

    this.playerNode = new AudioWorkletNode(context, "kiosk-player", {
      numberOfInputs: 0,
      outputChannelCount: [1],
    })
    this.playerNode.connect(context.destination)
    this.playerNode.port.onmessage = (event: MessageEvent<PlayerMessage>) => {
      this.handlePlayer(event.data)
    }

    this.micNode = new AudioWorkletNode(context, "kiosk-mic", { numberOfOutputs: 0 })
    context.createMediaStreamSource(this.stream).connect(this.micNode)
    this.micNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(event.data)
      }
    }

    await this.openSocket(session, baseUrl)
  }

  private openSocket(session: KioskSession, baseUrl: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(voiceSocketUrl(session, baseUrl))
      socket.binaryType = "arraybuffer"
      this.socket = socket

      socket.onopen = () => resolve()
      socket.onerror = () => {
        if (this.closed) return
        this.handlers.onError("Se perdió la conexión de voz")
        reject(new Error("Se perdió la conexión de voz"))
      }
      socket.onclose = (event) => {
        if (this.closed) return
        this.releaseDeferred()
        if (this.finished) {
          this.handlers.onFinished()
          return
        }
        // The backend never said the visit was over, so it is not over. It closes on purpose
        // exactly once -- `session.finished`, then code 1000 -- and every other close is
        // something breaking: the transcription session upstream ending, a fault in the
        // turn, a network that came and went. Treating those as a completed visit is what
        // put "Atención finalizada" in front of a customer who was still mid-conversation.
        //
        // A policy close is the exception. The backend refused the connection for a reason
        // that will not have changed by the time a retry arrives, so reconnecting would only
        // fail the same way.
        this.handlers.onDropped(event.code !== CLOSE_POLICY_VIOLATION)
      }
      socket.onmessage = (event: MessageEvent) => {
        if (typeof event.data === "string") {
          this.handleFrame(JSON.parse(event.data) as ServerFrame)
          return
        }
        // Anything not JSON is speech: PCM16 straight to the player, no decode step. It is
        // tagged with the line it belongs to, so a cancellation can drop one sentence
        // without silencing the one queued behind it.
        const buffer = event.data as ArrayBuffer
        this.playing = true
        this.playerNode?.port.postMessage(
          { type: "chunk", speechId: this.currentSpeechId, buffer },
          [buffer],
        )
      }
    })
  }

  private handleFrame(frame: ServerFrame): void {
    switch (frame.type) {
      case "session.state":
        this.applyState(frame.value as VoiceSessionState)
        break
      case "transcript.delta":
        this.upsertCaption(frame.item_id ?? "", "user", frame.text ?? "", false, true)
        break
      case "transcript.completed":
        this.upsertCaption(frame.item_id ?? "", "user", frame.text ?? "", true, false)
        break
      case "speech.begin":
        this.beginLine(frame.speech_id ?? "", frame.text ?? "")
        break
      case "speech.end":
        this.completeLine(frame.speech_id ?? "")
        break
      case "speech.cancel":
        // The customer talked over the kiosk. Drop what is queued for *that line* rather
        // than letting it finish -- that is the whole of barge-in on this side. Scoping it
        // matters: a cancel arriving after the next line was already queued used to wipe
        // that one too, which is how an answer went unheard.
        this.playerNode?.port.postMessage({ type: "flush", speechId: frame.speech_id ?? null })
        break
      case "turn.analysis": {
        const payload = frame.payload as TurnAnalysis
        this.defer(() => this.handlers.onAnalysis(payload))
        break
      }
      case "turn.result": {
        const payload = frame.payload as FlowResult
        this.defer(() => this.handlers.onResult(payload))
        break
      }
      case "session.finished":
        this.finished = true
        this.releaseDeferred()
        this.handlers.onFinished()
        break
      case "error":
        this.releaseDeferred()
        this.handlers.onError(frame.message ?? "No pude procesar tu solicitud")
        break
    }
  }

  // ------------------------------------------------------------- presentation gate

  /**
   * Hold a business frame until the sentence it belongs to is audible.
   *
   * The backend sends the flow frame, then `speech.begin`, then the audio. Applied in that
   * order the card repaints, the route changes and the whole sentence appears in writing
   * before the kiosk has said a word of it.
   */
  private defer(apply: () => void): void {
    this.deferred.push(apply)
    this.deferredAfterSeq = this.lineSeq
    if (this.deferredTimer === null) {
      this.deferredTimer = setTimeout(() => this.releaseDeferred(), PRESENTATION_CAP_MS)
    }
  }

  private releaseDeferred(): void {
    if (this.deferredTimer !== null) {
      clearTimeout(this.deferredTimer)
      this.deferredTimer = null
    }
    const pending = this.deferred
    this.deferred = []
    for (const apply of pending) apply()
  }

  // --------------------------------------------------------------------- speech

  private beginLine(speechId: string, text: string): void {
    if (!speechId) return
    this.lineSeq += 1
    this.lines.set(speechId, {
      seq: this.lineSeq,
      text,
      complete: false,
      played: 0,
      queued: 0,
      revealed: 0,
    })
    this.currentSpeechId = speechId
  }

  private completeLine(speechId: string): void {
    const line = this.lines.get(speechId)
    if (line) line.complete = true
    this.playerNode?.port.postMessage({ type: "end", speechId })
  }

  private handlePlayer(message: PlayerMessage): void {
    if (message.type === "drained") {
      this.playing = false
      this.releaseDeferred()
      if (this.pendingState) {
        const value = this.pendingState
        this.pendingState = null
        this.handlers.onState(value)
      }
      const waiters = this.drainWaiters
      this.drainWaiters = []
      for (const resolve of waiters) resolve()
      return
    }

    const speechId = message.speechId ?? ""
    const line = this.lines.get(speechId)
    if (!line) return

    if (message.type === "ended") {
      // A line that played out shows its whole text; one cut short by an interruption keeps
      // the truncation, because that is what the person actually heard.
      if (!message.cancelled) line.revealed = line.text.length
      this.lines.delete(speechId)
      if (this.currentSpeechId === speechId) this.currentSpeechId = null
      this.upsertCaption(speechId, "assistant", line.text.slice(0, line.revealed), true, false)
      return
    }

    line.played = message.playedSamples ?? line.played
    line.queued = message.queuedSamples ?? line.queued
    if (line.seq > this.deferredAfterSeq) this.releaseDeferred()
    this.reveal(speechId, line)
  }

  private reveal(speechId: string, line: SpokenLine): void {
    const estimate = (line.text.length / SPEECH_CHARS_PER_SECOND) * SAMPLE_RATE
    const total = line.complete ? line.queued : Math.max(line.queued, estimate)
    if (total <= 0) return
    const chars = Math.floor((line.played / total) * line.text.length)
    // Back to the last word boundary: a word half on screen before it has been said is the
    // same problem as the whole sentence being early, in miniature.
    const boundary = line.text.lastIndexOf(" ", Math.min(chars, line.text.length))
    const next = chars >= line.text.length ? line.text.length : Math.max(boundary, 0)
    if (next <= line.revealed) return
    line.revealed = next
    this.upsertCaption(speechId, "assistant", line.text.slice(0, next), false, false)
  }

  private applyState(value: VoiceSessionState): void {
    // The backend says "listening" as soon as it has sent the last byte, which is well
    // before the last byte is heard. Anything that contradicts the speaker waits for it.
    if (value !== "speaking" && this.playing) {
      this.pendingState = value
      return
    }
    this.pendingState = null
    this.handlers.onState(value)
  }

  private upsertCaption(
    id: string,
    role: "user" | "assistant",
    text: string,
    completed: boolean,
    append: boolean,
  ): void {
    if (!id) return
    const existing = this.captions.find((caption) => caption.id === id)
    // Nothing appears until there is something to show. An assistant bubble created at
    // `speech.begin` would be an empty box on screen for as long as the speech takes to
    // reach the speaker -- the same jump ahead of the voice, just with no words in it.
    if (!existing && !text) return
    if (existing) {
      existing.text = append ? `${existing.text}${text}` : text
      existing.completed = completed
    } else {
      this.captions = [...this.captions, { id, role, text, completed }]
    }
    this.handlers.onCaptions([...this.captions])
  }

  // -------------------------------------------------------------------- controls

  /** Tell the backend an out-of-band step finished. Identification is the only one. */
  resync(): void {
    this.send({ type: "client.resync" })
  }

  /**
   * The customer took the turn without saying anything -- they started typing the answer
   * while the kiosk was still explaining it. Treated exactly like talking over it: the
   * sentence stops where it is, here and on the backend.
   */
  bargeIn(): void {
    this.playerNode?.port.postMessage({ type: "flush", speechId: this.currentSpeechId })
    this.send({ type: "client.barge_in" })
  }

  /** Resolves when everything handed to the speaker has been heard, or the wait runs out. */
  drain(timeoutMs = 10_000): Promise<void> {
    if (!this.playing || !this.playerNode) return Promise.resolve()
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.drainWaiters = this.drainWaiters.filter((waiter) => waiter !== settle)
        resolve()
      }, timeoutMs)
      const settle = () => {
        clearTimeout(timer)
        resolve()
      }
      this.drainWaiters.push(settle)
    })
  }

  private send(payload: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload))
    }
  }

  /**
   * Stop listening and end the session. Deliberately separate from `closeAudio`: the socket
   * closing says nothing about whether the last line has been heard, and tearing the audio
   * graph down on that signal is what silenced it.
   */
  closeSocket(): void {
    this.closed = true
    if (this.deferredTimer !== null) {
      clearTimeout(this.deferredTimer)
      this.deferredTimer = null
    }
    this.deferred = []
    this.micNode?.port.close()
    this.micNode?.disconnect()
    this.stream?.getTracks().forEach((track) => track.stop())
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      this.socket.close()
    }
    this.socket = null
    this.stream = null
    this.micNode = null
  }

  /** Destroys whatever is still queued for the speaker. Call it after `drain`. */
  closeAudio(): void {
    this.playerNode?.port.close()
    this.playerNode?.disconnect()
    void this.context?.close().catch(() => {
      // Nothing depends on the context's own teardown; the session ended with the socket.
    })
    this.playerNode = null
    this.context = null
    this.lines.clear()
    this.currentSpeechId = null
    this.playing = false
    const waiters = this.drainWaiters
    this.drainWaiters = []
    for (const resolve of waiters) resolve()
    this.captions = []
  }

  close(): void {
    this.closeSocket()
    this.closeAudio()
  }
}
