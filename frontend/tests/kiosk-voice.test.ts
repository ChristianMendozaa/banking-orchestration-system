// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest"

import {
  KioskVoiceConnection,
  SAMPLE_RATE,
  voiceSocketUrl,
  type VoiceCaption,
} from "../lib/kiosk-voice"
import type { KioskSession } from "../lib/types"

const session: KioskSession = {
  session_id: "session-1",
  session_token: "secret-token",
  status: "CREATED",
  expires_at: "2099-01-01T00:00:00Z",
}

class FakeSocket {
  static last: FakeSocket | null = null
  static readonly OPEN = 1
  readyState = 1
  binaryType = ""
  sent: (string | ArrayBuffer)[] = []
  closed = false
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null

  constructor(readonly url: string) {
    FakeSocket.last = this
    queueMicrotask(() => this.onopen?.())
  }

  send(payload: string | ArrayBuffer) {
    this.sent.push(payload)
  }

  close() {
    this.closed = true
  }

  deliver(frame: object) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }

  /** The socket going away. 1000 is a normal close, 1011 a backend fault, 1008 a refusal. */
  drop(code = 1011) {
    this.readyState = 3
    this.onclose?.({ code })
  }
}

const playerMessages: unknown[] = []

class FakeWorkletNode {
  static player: FakeWorkletNode | null = null
  port = {
    onmessage: null as ((event: { data: unknown }) => void) | null,
    postMessage: (data: unknown) => playerMessages.push(data),
    close: () => {},
  }
  constructor(_context: unknown, name: string) {
    if (name === "kiosk-player") FakeWorkletNode.player = this
  }
  connect() {}
  disconnect() {}
}

/** What the speaker reports back: the only thing that knows what was actually heard. */
function fromPlayer(message: Record<string, unknown>) {
  FakeWorkletNode.player!.port.onmessage!({ data: message })
}

class FakeAudioContext {
  static lastSampleRate = 0
  destination = {}
  audioWorklet = { addModule: vi.fn(async () => {}) }
  constructor(options: { sampleRate: number }) {
    FakeAudioContext.lastSampleRate = options.sampleRate
  }
  createMediaStreamSource() {
    return { connect: () => {} }
  }
  async close() {}
}

function handlers() {
  return {
    onState: vi.fn(),
    onCaptions: vi.fn(),
    onAnalysis: vi.fn(),
    onResult: vi.fn(),
    onFinished: vi.fn(),
    onDropped: vi.fn(),
    onError: vi.fn(),
  }
}

beforeEach(() => {
  playerMessages.length = 0
  FakeSocket.last = null
  FakeWorkletNode.player = null
  vi.stubGlobal("WebSocket", FakeSocket)
  vi.stubGlobal("AudioContext", FakeAudioContext)
  vi.stubGlobal("AudioWorkletNode", FakeWorkletNode)
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: () => {} }] })),
    },
  })
})

describe("voiceSocketUrl", () => {
  it("carries the session token in the query string", () => {
    // A browser cannot set headers on a WebSocket handshake, which is the whole reason the
    // token is not in X-Session-Token here like it is on every other kiosk call.
    const url = new URL(voiceSocketUrl(session, "http://localhost:8000"))
    expect(url.protocol).toBe("ws:")
    expect(url.pathname).toBe("/api/v1/kiosk/sessions/session-1/voice")
    expect(url.searchParams.get("token")).toBe("secret-token")
  })

  it("upgrades a secure origin to wss", () => {
    expect(voiceSocketUrl(session, "https://kiosco.example")).toMatch(/^wss:\/\//)
  })
})

describe("KioskVoiceConnection", () => {
  it("captures at the one rate both ends of the channel use", async () => {
    // 24 kHz end to end: the transcription session accepts nothing else and the speech
    // model returns it, so nothing has to resample.
    const connection = new KioskVoiceConnection(handlers())
    await connection.connect(session, "http://localhost:8000")
    expect(FakeAudioContext.lastSampleRate).toBe(SAMPLE_RATE)
    connection.close()
  })

  it("asks for echo cancellation, without which it transcribes itself", async () => {
    const connection = new KioskVoiceConnection(handlers())
    await connection.connect(session, "http://localhost:8000")
    const constraints = vi.mocked(navigator.mediaDevices.getUserMedia).mock.calls[0][0]
    expect(constraints).toMatchObject({ audio: { echoCancellation: true } })
    connection.close()
  })

  it("holds a card back until the sentence it belongs to is audible", async () => {
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")
    const socket = FakeSocket.last!

    socket.deliver({ type: "session.state", value: "thinking" })
    socket.deliver({ type: "turn.analysis", payload: { requirement_id: "r-1" } })
    socket.deliver({ type: "speech.begin", speech_id: "s-1", text: "Un momento." })
    socket.onmessage?.({ data: new ArrayBuffer(8) })

    expect(callbacks.onState).toHaveBeenCalledWith("thinking")
    // The backend sends the flow frame just ahead of the line it belongs to. Applied on
    // arrival, the card repaints and the sentence appears in writing before the kiosk has
    // said a word of it -- which is the whole complaint about the screen running ahead.
    expect(callbacks.onAnalysis).not.toHaveBeenCalled()
    expect(playerMessages.at(-1)).toMatchObject({ type: "chunk", speechId: "s-1" })

    fromPlayer({
      type: "progress",
      speechId: "s-1",
      playedSamples: 240,
      queuedSamples: 24_000,
    })
    expect(callbacks.onAnalysis).toHaveBeenCalledWith({ requirement_id: "r-1" })
    connection.close()
  })

  it("shows a card whose line is never spoken rather than stranding it", async () => {
    // A transition the backend has already spoken once is deduplicated and no audio
    // follows, so the gate cannot wait on a line that is not coming.
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")
    vi.useFakeTimers()
    try {
      FakeSocket.last!.deliver({ type: "turn.result", payload: { requirement_id: "r-1" } })
      expect(callbacks.onResult).not.toHaveBeenCalled()
      vi.advanceTimersByTime(1_500)
      expect(callbacks.onResult).toHaveBeenCalledWith({ requirement_id: "r-1" })
    } finally {
      vi.useRealTimers()
    }
    connection.close()
  })

  it("drops the interrupted line by name, not everything in the speaker", async () => {
    const connection = new KioskVoiceConnection(handlers())
    await connection.connect(session, "http://localhost:8000")
    FakeSocket.last!.deliver({ type: "speech.cancel", speech_id: "s-1" })
    // Finishing the sentence over someone who has started talking is the behaviour this
    // channel exists to avoid. Naming the line is what keeps the cancellation from also
    // silencing the answer already queued behind it.
    expect(playerMessages).toContainEqual({ type: "flush", speechId: "s-1" })
    connection.close()
  })

  it("waits for the speaker before the audio graph may be torn down", async () => {
    // Speech arrives far faster than it plays, so at the moment the socket closes most of
    // the last sentence is still queued. Closing the context on that signal is what made a
    // quick answer cost the customer the line that came after it.
    const connection = new KioskVoiceConnection(handlers())
    await connection.connect(session, "http://localhost:8000")
    const socket = FakeSocket.last!

    socket.deliver({ type: "speech.begin", speech_id: "s-1", text: "Tu ticket es 41." })
    socket.onmessage?.({ data: new ArrayBuffer(8) })

    let drained = false
    const waiting = connection.drain().then(() => {
      drained = true
    })
    await Promise.resolve()
    expect(drained).toBe(false)

    fromPlayer({ type: "drained" })
    await waiting
    expect(drained).toBe(true)
    connection.close()
  })

  it("reports the state the customer is in, not the one the backend has moved on to", async () => {
    // "listening" is sent as soon as the last byte is on the wire, which is well before it
    // is heard. Showing it then tells someone the kiosk is waiting for them while it is
    // still talking.
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")
    const socket = FakeSocket.last!

    socket.deliver({ type: "speech.begin", speech_id: "s-1", text: "Tu ticket es 41." })
    socket.onmessage?.({ data: new ArrayBuffer(8) })
    socket.deliver({ type: "session.state", value: "listening" })
    expect(callbacks.onState).not.toHaveBeenCalledWith("listening")

    fromPlayer({ type: "drained" })
    expect(callbacks.onState).toHaveBeenCalledWith("listening")
    connection.close()
  })

  it("builds captions from partial transcripts and the kiosk's own lines", async () => {
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")
    const socket = FakeSocket.last!

    socket.deliver({ type: "transcript.delta", item_id: "i-1", text: "Quiero " })
    socket.deliver({ type: "transcript.delta", item_id: "i-1", text: "reportar" })
    socket.deliver({
      type: "transcript.completed",
      item_id: "i-1",
      text: "Quiero reportar el robo de mi tarjeta",
    })
    socket.deliver({
      type: "speech.begin",
      speech_id: "s-1",
      text: "Un momento, estoy revisando eso.",
    })

    const latest = () =>
      (callbacks.onCaptions.mock.calls.at(-1)![0] as VoiceCaption[]).at(-1)

    // Nothing of the kiosk's own line is on screen yet. Writing it out at `speech.begin`
    // is exactly the subtitle that finished the sentence before the voice had started it.
    expect(latest()!.role).toBe("user")

    socket.deliver({ type: "speech.end", speech_id: "s-1" })
    fromPlayer({
      type: "progress",
      speechId: "s-1",
      playedSamples: 24_000,
      queuedSamples: 48_000,
    })
    // Half the line has been heard, so half of it is on screen -- and to a word boundary,
    // because half a word is the same problem in miniature.
    expect(latest()).toEqual({
      id: "s-1",
      role: "assistant",
      text: "Un momento,",
      completed: false,
    })

    fromPlayer({ type: "ended", speechId: "s-1", cancelled: false })
    expect(latest()).toEqual({
      id: "s-1",
      role: "assistant",
      text: "Un momento, estoy revisando eso.",
      completed: true,
    })

    const captions = callbacks.onCaptions.mock.calls.at(-1)![0] as VoiceCaption[]
    expect(captions[0]).toEqual({
      id: "i-1",
      role: "user",
      text: "Quiero reportar el robo de mi tarjeta",
      completed: true,
    })
    connection.close()
  })

  it("reports a finished session once, and not again after closing", async () => {
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")
    const socket = FakeSocket.last!

    socket.deliver({ type: "session.finished" })
    expect(callbacks.onFinished).toHaveBeenCalledTimes(1)

    connection.close()
    socket.drop(1000)
    expect(callbacks.onFinished).toHaveBeenCalledTimes(1)
    expect(callbacks.onDropped).not.toHaveBeenCalled()
  })

  it("treats a close the backend never announced as a drop, not as a finished visit", async () => {
    // The bug: any close at all was reported as a completed visit, so an upstream
    // transcription session going away mid-conversation put "Atención finalizada" on screen
    // in front of a customer who was three questions in and still talking.
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")

    FakeSocket.last!.drop(1011)

    expect(callbacks.onFinished).not.toHaveBeenCalled()
    expect(callbacks.onDropped).toHaveBeenCalledWith(true)
  })

  it("does not offer to retry a close the backend made on purpose", async () => {
    // A policy refusal -- a disallowed origin, a session that cannot be served -- will be
    // refused again on the next attempt, so reconnecting only fails more slowly.
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")

    FakeSocket.last!.drop(1008)

    expect(callbacks.onDropped).toHaveBeenCalledWith(false)
  })
})
