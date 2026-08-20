import type { FlowResult, KioskSession, TurnAnalysis } from "@/lib/types"

// Both directions of the channel run at this rate. The transcription session accepts only
// 24 kHz PCM and the speech model returns it, so matching the AudioContext to it means the
// browser never resamples and never decodes.
export const SAMPLE_RATE = 24_000
const WORKLET_URL = "/kiosk-audio-worklet.js"

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
  onFinished: () => void
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
 */
export class KioskVoiceConnection {
  private socket: WebSocket | null = null
  private context: AudioContext | null = null
  private stream: MediaStream | null = null
  private micNode: AudioWorkletNode | null = null
  private playerNode: AudioWorkletNode | null = null
  private captions: VoiceCaption[] = []
  private closed = false

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
      socket.onclose = () => {
        if (this.closed) return
        this.handlers.onFinished()
      }
      socket.onmessage = (event: MessageEvent) => {
        if (typeof event.data === "string") {
          this.handleFrame(JSON.parse(event.data) as ServerFrame)
          return
        }
        // Anything not JSON is speech: PCM16 straight to the player, no decode step.
        this.playerNode?.port.postMessage(event.data, [event.data as ArrayBuffer])
      }
    })
  }

  private handleFrame(frame: ServerFrame): void {
    switch (frame.type) {
      case "session.state":
        this.handlers.onState(frame.value as VoiceSessionState)
        break
      case "transcript.delta":
        this.upsertCaption(frame.item_id ?? "", "user", frame.text ?? "", false, true)
        break
      case "transcript.completed":
        this.upsertCaption(frame.item_id ?? "", "user", frame.text ?? "", true, false)
        break
      case "speech.begin":
        this.upsertCaption(
          frame.speech_id ?? "",
          "assistant",
          frame.text ?? "",
          true,
          false,
        )
        break
      case "speech.cancel":
        // The customer talked over the kiosk. Drop what is queued rather than letting it
        // finish -- that is the whole of barge-in on this side.
        this.playerNode?.port.postMessage("flush")
        break
      case "turn.analysis":
        this.handlers.onAnalysis(frame.payload as TurnAnalysis)
        break
      case "turn.result":
        this.handlers.onResult(frame.payload as FlowResult)
        break
      case "session.finished":
        this.handlers.onFinished()
        break
      case "error":
        this.handlers.onError(frame.message ?? "No pude procesar tu solicitud")
        break
    }
  }

  private upsertCaption(
    id: string,
    role: "user" | "assistant",
    text: string,
    completed: boolean,
    append: boolean,
  ): void {
    if (!id || !text) return
    const existing = this.captions.find((caption) => caption.id === id)
    if (existing) {
      existing.text = append ? `${existing.text}${text}` : text
      existing.completed = completed
    } else {
      this.captions = [...this.captions, { id, role, text, completed }]
    }
    this.handlers.onCaptions([...this.captions])
  }

  /** Tell the backend an out-of-band step finished. Identification is the only one. */
  resync(): void {
    this.send({ type: "client.resync" })
  }

  private send(payload: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload))
    }
  }

  close(): void {
    this.closed = true
    this.micNode?.port.close()
    this.micNode?.disconnect()
    this.playerNode?.disconnect()
    this.stream?.getTracks().forEach((track) => track.stop())
    void this.context?.close().catch(() => {
      // The socket close below is what actually ends the session.
    })
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      this.socket.close()
    }
    this.socket = null
    this.context = null
    this.stream = null
    this.micNode = null
    this.playerNode = null
    this.captions = []
  }
}
