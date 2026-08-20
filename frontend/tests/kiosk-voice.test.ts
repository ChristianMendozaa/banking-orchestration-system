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
  onclose: (() => void) | null = null
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
}

const playerMessages: unknown[] = []

class FakeWorkletNode {
  port = {
    onmessage: null as ((event: MessageEvent) => void) | null,
    postMessage: (data: unknown) => playerMessages.push(data),
    close: () => {},
  }
  connect() {}
  disconnect() {}
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
    onError: vi.fn(),
  }
}

beforeEach(() => {
  playerMessages.length = 0
  FakeSocket.last = null
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

  it("routes flow frames to the business callbacks and audio to the player", async () => {
    const callbacks = handlers()
    const connection = new KioskVoiceConnection(callbacks)
    await connection.connect(session, "http://localhost:8000")
    const socket = FakeSocket.last!

    socket.deliver({ type: "session.state", value: "thinking" })
    socket.deliver({ type: "turn.analysis", payload: { requirement_id: "r-1" } })
    socket.deliver({ type: "turn.result", payload: { requirement_id: "r-1" } })
    socket.onmessage?.({ data: new ArrayBuffer(8) })

    expect(callbacks.onState).toHaveBeenCalledWith("thinking")
    expect(callbacks.onAnalysis).toHaveBeenCalledWith({ requirement_id: "r-1" })
    expect(callbacks.onResult).toHaveBeenCalledWith({ requirement_id: "r-1" })
    expect(playerMessages.at(-1)).toBeInstanceOf(ArrayBuffer)
    connection.close()
  })

  it("drops queued audio the moment the customer interrupts", async () => {
    const connection = new KioskVoiceConnection(handlers())
    await connection.connect(session, "http://localhost:8000")
    FakeSocket.last!.deliver({ type: "speech.cancel", speech_id: "s-1" })
    // Finishing the sentence over someone who has started talking is the behaviour this
    // channel exists to avoid, so the queue is dropped rather than faded out.
    expect(playerMessages).toContain("flush")
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
    socket.deliver({ type: "speech.begin", speech_id: "s-1", text: "Un momento." })

    const captions = callbacks.onCaptions.mock.calls.at(-1)![0] as VoiceCaption[]
    expect(captions).toEqual([
      {
        id: "i-1",
        role: "user",
        text: "Quiero reportar el robo de mi tarjeta",
        completed: true,
      },
      { id: "s-1", role: "assistant", text: "Un momento.", completed: true },
    ])
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
    socket.onclose?.()
    expect(callbacks.onFinished).toHaveBeenCalledTimes(1)
  })
})
