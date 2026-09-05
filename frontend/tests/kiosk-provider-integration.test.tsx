// @module-tag functional
// @module-tag integration
// @module-tag regression
// @vitest-environment jsdom

import { act, render, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  createSession: vi.fn(),
  sessionRequest: vi.fn(),
  replace: vi.fn(),
  createAgent: vi.fn(),
  newRealtimeSession: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  usePathname: () => "/kiosco",
  useRouter: () => ({ replace: mocks.replace }),
}))

vi.mock("../lib/kiosk-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/kiosk-api")>()
  return {
    ...original,
    createKioskSession: mocks.createSession,
    kioskSessionRequest: mocks.sessionRequest,
  }
})

vi.mock("@/lib/kiosk-realtime-agent", () => ({
  createKioskRealtimeAgent: mocks.createAgent,
}))

// The provider reaches the SDK through a dynamic import, so the substitution has to be
// hoisted: a `doMock` registered after the provider module is loaded never takes effect.
vi.mock("@openai/agents/realtime", () => ({
  RealtimeSession: function RealtimeSession(...args: unknown[]) {
    return mocks.newRealtimeSession(...args)
  },
}))

import {
  KioskProvider,
  useKiosk,
} from "../components/providers/kiosk-provider"
import type { KioskRealtimeCallbacks } from "../lib/kiosk-realtime"

describe("KioskProvider text flow", () => {
  beforeEach(() => {
    sessionStorage.clear()
    mocks.createSession.mockReset()
    mocks.sessionRequest.mockReset()
    mocks.replace.mockReset()
  })

  it("creates, retains, and processes a session without opening the voice transport", async () => {
    const session = {
      session_id: "session-text",
      session_token: "token",
      status: "CREATED",
      expires_at: "2099-01-01T00:00:00Z",
    }
    const analysis = {
      requirement_id: "requirement-text",
      status: "AWAITING_CONFIRMATION",
      summary: "Bloqueo de tarjeta.",
      customer_summary: "Necesitas bloquear tu tarjeta.",
      category: "BLOQUEO_TARJETA",
      priority: "ALTO",
      consultation_level: "SENSIBLE",
      confidence: 0.99,
      clarification_question: null,
      pii_types: [],
      next_action: "CONFIRM",
      speech_text: "Confirma si necesitas bloquear tu tarjeta.",
    }
    mocks.createSession.mockResolvedValue(session)
    mocks.sessionRequest.mockImplementation(
      async (_session: unknown, suffix: string) =>
        suffix === "/turns" ? analysis : { accepted: 2 },
    )

    let kiosk: ReturnType<typeof useKiosk> | null = null
    function Probe() {
      kiosk = useKiosk()
      return null
    }
    render(
      <KioskProvider>
        <Probe />
      </KioskProvider>,
    )
    await waitFor(() => expect(kiosk?.hydrated).toBe(true))

    await act(async () => kiosk!.beginSession(true))
    act(() => kiosk!.selectInteractionMode("text"))
    await act(async () => kiosk!.submitTextTurn("Necesito bloquear mi tarjeta"))

    const current = kiosk as unknown as ReturnType<typeof useKiosk>
    expect(mocks.createSession).toHaveBeenCalledWith(true)
    expect(current.interactionMode).toBe("text")
    expect(current.analysis?.requirement_id).toBe("requirement-text")
    await waitFor(() =>
      expect(mocks.sessionRequest).toHaveBeenCalledWith(
        session,
        "/conversation/messages",
        expect.objectContaining({ method: "POST" }),
      ),
    )
  })
})

describe("KioskProvider voice turn arbitration", () => {
  type Handler = (...args: unknown[]) => void

  class FakeRealtimeSession {
    handlers = new Map<string, Handler[]>()
    transportHandlers = new Map<string, Handler[]>()
    muted = false
    connect = vi.fn(async () => {})
    close = vi.fn()
    sendMessage = vi.fn()
    interrupt = vi.fn()
    mute = vi.fn((value: boolean) => {
      this.muted = value
    })
    transport = {
      status: "connected" as const,
      updateSessionConfig: vi.fn(),
      sendEvent: vi.fn(),
      on: (event: string, handler: Handler) => {
        const existing = this.transportHandlers.get(event) ?? []
        this.transportHandlers.set(event, [...existing, handler])
      },
    }

    on(event: string, handler: Handler) {
      const existing = this.handlers.get(event) ?? []
      this.handlers.set(event, [...existing, handler])
    }

    emit(event: string, ...args: unknown[]) {
      ;(this.handlers.get(event) ?? []).forEach((handler) => handler(...args))
    }

    /** Raw server events reach the provider through the `transport_event` listener. */
    emitTransportEvent(type: string, responseId?: string) {
      // Real server events name the response they belong to. The floor needs that: the
      // events that end a cancelled response arrive after the replacement has started.
      const payload: Record<string, unknown> = { type }
      if (responseId) {
        if (type.startsWith("response.")) payload.response = { id: responseId }
        else payload.response_id = responseId
      }
      this.emit("transport_event", payload)
    }
  }

  const session = {
    session_id: "session-voice",
    session_token: "token",
    status: "AWAITING_IDENTIFICATION",
    expires_at: "2099-01-01T00:00:00Z",
  }
  const identifyResult = {
    session_id: session.session_id,
    requirement_id: "requirement-voice",
    status: "AWAITING_IDENTIFICATION",
    next_action: "IDENTIFY",
    customer_summary: "Necesitas bloquear tu tarjeta.",
    identification_status: "PENDIENTE",
    resolution_type: null,
    ticket: null,
    executive: null,
    response: null,
    speech_text: "Escribe tu CI en el campo protegido.",
    speech_plan: {
      intent: "IDENTIFY",
      facts: { accion: "escribir su CI en el campo protegido de la pantalla" },
      verbatim: ["No escribas contraseñas, PIN ni datos financieros."],
      guidance: "Pídele que haga lo que dice `accion`.",
      fallback_text: "Escribe tu CI en el campo protegido.",
    },
    conversation_can_continue: false,
  }
  const handoffResult = {
    ...identifyResult,
    status: "ASSIGNED",
    next_action: "COMPLETE",
    identification_status: "IDENTIFICADO",
    resolution_type: "HUMAN",
    ticket: { id: "ticket-1", number: 42, status: "PENDIENTE", estimated_wait_minutes: 3 },
    speech_text: "Tu ticket es 42. Dirígete a Ventanilla 3 con María Torres.",
    speech_plan: {
      intent: "HANDOFF",
      facts: { ticket: "42", ventanilla: "Ventanilla 3", ejecutivo: "María Torres" },
      verbatim: ["María Torres"],
      guidance: "Dale el ticket, la ventanilla y el nombre.",
      fallback_text: "Tu ticket es 42.",
    },
  }

  let realtime: FakeRealtimeSession

  async function connectedKiosk(options: { listening?: boolean } = {}) {
    const listening = options.listening ?? false
    const storedSession = listening
      ? { ...session, status: "LISTENING" }
      : session
    const storedResult = listening ? null : identifyResult
    realtime = new FakeRealtimeSession()
    mocks.newRealtimeSession.mockImplementation(() => realtime)
    mocks.createAgent.mockImplementation(() => ({}))
    mocks.sessionRequest.mockImplementation(async (_session: unknown, suffix: string) => {
      if (suffix === "") {
        return {
          session_id: storedSession.session_id,
          status: storedSession.status,
          result: storedResult,
        }
      }
      if (suffix === "/conversation/messages") return { messages: [], accepted: 0 }
      if (suffix === "/realtime-token") {
        return {
          value: "ek_test",
          session: {
            model: "gpt-realtime-2.1-mini",
            instructions: "Eres la asistente virtual de un kiosco del banco.",
            voice: "marin",
            audio_input: {
              noise_reduction: { type: "near_field" },
              transcription: { model: "gpt-realtime-whisper", language: "es" },
              turn_detection: { type: "semantic_vad" },
            },
          },
        }
      }
      if (suffix === "/identification") return handoffResult
      throw new Error(`unexpected ${suffix}`)
    })

    let kiosk: ReturnType<typeof useKiosk> | null = null
    function Probe() {
      kiosk = useKiosk()
      return null
    }
    sessionStorage.setItem(
      "orquestacion_kiosk_flow_v4",
      JSON.stringify({
        session: storedSession,
        analysis: null,
        result: storedResult,
        isClarification: false,
        interactionMode: "voice",
      }),
    )
    render(
      <KioskProvider>
        <Probe />
      </KioskProvider>,
    )
    await waitFor(() => expect(kiosk?.hydrated).toBe(true))
    await act(async () => {
      await kiosk!.connectVoice()
    })
    return kiosk as unknown as ReturnType<typeof useKiosk>
  }

  beforeEach(() => {
    sessionStorage.clear()
    vi.resetModules()
    mocks.createSession.mockReset()
    mocks.sessionRequest.mockReset()
    mocks.replace.mockReset()
    mocks.createAgent.mockReset()
    mocks.newRealtimeSession.mockReset()
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: { mediaDevices: { getUserMedia: vi.fn() } },
    })
  })

  it("never sends a spoken turn to /turns while the CI field is open", async () => {
    // The reported failure: the session refuses `POST /turns` for the whole time it is
    // AWAITING_IDENTIFICATION, the 409 came back through the tool as "no pudiste consultar
    // el sistema, discúlpate", and the customer standing in front of the CI field heard the
    // kiosk say it had lost access and ask them to try again.
    await connectedKiosk()
    const callbacks = mocks.createAgent.mock.calls[0][0] as KioskRealtimeCallbacks
    mocks.sessionRequest.mockClear()

    const result = await callbacks.processSpokenTurn("Ya lo estoy escribiendo", "call-1")

    expect(result).toEqual({ kind: "awaiting_identification" })
    expect(
      mocks.sessionRequest.mock.calls.some(([, suffix]) => suffix === "/turns"),
    ).toBe(false)
  })

  it("cuts off the obsolete CI prompt and injects the closing exactly once", async () => {
    const kiosk = await connectedKiosk()
    const callbacks = mocks.createAgent.mock.calls[0][0] as KioskRealtimeCallbacks
    realtime.sendMessage.mockClear()
    realtime.mute.mockClear()

    // The model is mid-sentence on "escribe tu CI en el campo protegido..." when the CI
    // lands. That sentence is obsolete; letting it finish and queueing the closing behind
    // it is what a fast typist heard as two unrelated turns in a row.
    act(() => realtime.emitTransportEvent("response.created"))
    await act(async () => {
      await kiosk.submitIdentification("6735666")
    })

    expect(realtime.interrupt).toHaveBeenCalledTimes(1)
    expect(realtime.sendMessage).toHaveBeenCalledTimes(1)
    const injected = String(realtime.sendMessage.mock.calls[0][0])
    expect(injected).toContain("Ya escribió su CI")
    // The injection states what happened and nothing else. It used to tell the model to
    // "say how this ends using what the last tool returned", which pointed at whatever the
    // last call happened to be -- an idle check-in, on the recorded session -- and the
    // customer was never told their ticket number.
    expect(injected).not.toMatch(/herramienta|despídete/i)

    // The outcome itself reaches the model the only way business data is allowed to: as a
    // tool result carrying the backend's own SpeechPlan.
    expect(callbacks.takePendingResult()).toEqual({
      kind: "flow",
      response: handoffResult,
    })
    expect(callbacks.takePendingResult()).toBeNull()

    // The microphone stays shut: the result is terminal, and the only thing the old
    // `mute(false)` bought was a path from the kiosk's speaker back into its own VAD.
    expect(realtime.mute).not.toHaveBeenCalledWith(false)
  })

  it("silences the CI prompt before the request, not after it comes back", async () => {
    // The reported symptom, and the reason the cut "does not always work": the interrupt
    // used to happen after `await`, so "escribe tu CI en el campo protegido" kept playing
    // for the whole round trip -- which creates the ticket and assigns an executive.
    const kiosk = await connectedKiosk()
    realtime.interrupt.mockClear()

    let releaseIdentification: (value: unknown) => void = () => {}
    mocks.sessionRequest.mockImplementationOnce(
      () => new Promise((resolve) => (releaseIdentification = resolve)),
    )

    act(() => realtime.emitTransportEvent("response.created", "resp_ci"))
    act(() => realtime.emitTransportEvent("output_audio_buffer.started", "resp_ci"))

    let submitted: Promise<unknown> = Promise.resolve()
    act(() => {
      submitted = kiosk.submitIdentification("6735666")
    })

    // Nothing has come back yet, and the speaker is already quiet.
    expect(realtime.interrupt).toHaveBeenCalledTimes(1)

    await act(async () => {
      releaseIdentification(handoffResult)
      await submitted
    })
  })

  it("does not let a stale answer reach the model after the conversation moved on", async () => {
    // The client already refused to *show* a superseded answer. It handed the same
    // response back to the tool anyway, so the model read out an answer to a question the
    // person had already replaced.
    const kiosk = await connectedKiosk({ listening: true })
    const callbacks = mocks.createAgent.mock.calls[0][0] as KioskRealtimeCallbacks

    let releaseTurn: (value: unknown) => void = () => {}
    mocks.sessionRequest.mockImplementationOnce(
      () => new Promise((resolve) => (releaseTurn = resolve)),
    )

    let routed: Promise<unknown> = Promise.resolve()
    act(() => {
      routed = callbacks.processSpokenTurn("¿Cuáles son los horarios?", "call-stale")
    })

    // The conversation moves on while the backend is still answering.
    await act(async () => {
      await kiosk.reset()
    })

    await act(async () => {
      releaseTurn(handoffResult)
    })

    await expect(routed).resolves.toMatchObject({ kind: "superseded" })
  })
})
