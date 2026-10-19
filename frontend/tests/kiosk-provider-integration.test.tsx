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
  type ResponseCreate = { type: string; response?: { instructions?: string; tool_choice?: string } }

  class FakeRealtimeSession {
    handlers = new Map<string, Handler[]>()
    transportHandlers = new Map<string, Handler[]>()
    history: unknown[] = []
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

    /** The customer talks: the turn detector fires, then the transcription lands. */
    say(itemId: string, transcript: string) {
      this.emitTransportEvent("input_audio_buffer.speech_started")
      this.emitTransportEvent("input_audio_buffer.speech_stopped")
      this.history = [
        ...this.history,
        {
          itemId,
          type: "message",
          role: "user",
          status: "completed",
          content: [{ type: "input_audio", audio: null, transcript }],
        },
      ]
      this.emit("history_updated", this.history)
    }

    /** The server acknowledges a requested response and finishes it, with no audio. */
    finishResponse(responseId: string) {
      this.emitTransportEvent("response.created", responseId)
      this.emitTransportEvent("response.done", responseId)
    }

    /** Every response the application asked for, in order. */
    responseRequests(): ResponseCreate[] {
      return this.transport.sendEvent.mock.calls
        .map(([event]) => event as ResponseCreate)
        .filter((event) => event.type === "response.create")
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
  const clarifyAnalysis = {
    session_id: session.session_id,
    requirement_id: "requirement-clarify",
    status: "NEEDS_CLARIFICATION",
    next_action: "CLARIFY",
    customer_summary: null,
    clarification_question: "¿Es tu tarjeta de débito o de crédito?",
    speech_text: "¿Es tu tarjeta de débito o de crédito?",
    speech_plan: {
      intent: "CLARIFY",
      facts: { pregunta: "¿Es tu tarjeta de débito o de crédito?" },
      verbatim: [],
      guidance: "Pregunta lo que falta.",
      fallback_text: "¿Es tu tarjeta de débito o de crédito?",
    },
    conversation_can_continue: false,
  }
  const automaticAnswer = {
    ...clarifyAnalysis,
    requirement_id: "requirement-auto",
    status: "RESOLVED",
    next_action: "COMPLETE",
    clarification_question: null,
    result: {
      ...identifyResult,
      requirement_id: "requirement-auto",
      status: "RESOLVED",
      next_action: "COMPLETE",
      resolution_type: "AUTOMATIC",
      customer_summary: "Horarios de atención",
      conversation_can_continue: true,
    },
  }

  let realtime: FakeRealtimeSession
  // The value from the latest render. What `connectedKiosk` returns is a snapshot, which is
  // enough for calling actions but not for reading state that changes afterwards.
  let latestKiosk: ReturnType<typeof useKiosk>
  // What `POST /turns` answers. Routed by path rather than queued with `mockImplementationOnce`,
  // because every transcript also syncs `/conversation/messages` around the turn.
  let answerTurn: (transcript: string) => Promise<unknown>

  function turnRequests(): string[] {
    return mocks.sessionRequest.mock.calls
      .filter(([, suffix]) => suffix === "/turns")
      .map(([, , init]) => JSON.parse(String((init as RequestInit).body)).transcript)
  }

  async function connectedKiosk(options: { listening?: boolean } = {}) {
    const listening = options.listening ?? false
    const storedSession = listening
      ? { ...session, status: "LISTENING" }
      : session
    const storedResult = listening ? null : identifyResult
    realtime = new FakeRealtimeSession()
    answerTurn = async () => {
      throw new Error("unexpected /turns")
    }
    mocks.newRealtimeSession.mockImplementation(() => realtime)
    mocks.createAgent.mockImplementation(() => ({}))
    mocks.sessionRequest.mockImplementation(
      async (_session: unknown, suffix: string, init?: RequestInit) => {
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
                turn_detection: {
                  type: "semantic_vad",
                  eagerness: "low",
                  create_response: false,
                  interrupt_response: true,
                },
              },
            },
          }
        }
        if (suffix === "/turns") {
          return answerTurn(JSON.parse(String(init?.body)).transcript)
        }
        if (suffix === "/identification") return handoffResult
        throw new Error(`unexpected ${suffix}`)
      },
    )

    let kiosk: ReturnType<typeof useKiosk> | null = null
    function Probe() {
      kiosk = useKiosk()
      latestKiosk = kiosk
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

  /** The greeting -- or the reconnect summary -- is heard out. */
  function openingHeard() {
    act(() => realtime.finishResponse("resp_opening"))
  }

  async function say(itemId: string, transcript: string) {
    await act(async () => {
      realtime.say(itemId, transcript)
    })
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

  describe("who decides when the kiosk speaks", () => {
    it("greets first and alone, and answers what was said over it afterwards", async () => {
      // 2026-10-14, session 20152c7d: the room was talking when the kiosk connected. It
      // answered the noise ("Claro, déjame verificar la petición por un momento", "Ya lo
      // estoy") and only then greeted. The opening line now goes out on its own, the noise
      // cannot cut it off, and what was said over it waits for it to end.
      await connectedKiosk({ listening: true })
      const [, sessionOptions] = mocks.newRealtimeSession.mock.calls[0] as [
        unknown,
        { config: { audio: { input: { turnDetection: Record<string, unknown> } } } },
      ]
      expect(sessionOptions.config.audio.input.turnDetection).toMatchObject({
        create_response: false,
        interruptResponse: false,
      })
      expect(mocks.createAgent).toHaveBeenCalledWith({
        instructions: "Eres la asistente virtual de un kiosco del banco.",
        voice: "marin",
      })

      answerTurn = async () => clarifyAnalysis
      await say("item-1", "¿Cuáles son los horarios de atención?")

      expect(realtime.responseRequests()).toHaveLength(1)
      expect(realtime.responseRequests()[0].response?.instructions).toContain(
        "Recién empieza la atención",
      )
      expect(realtime.responseRequests()[0].response?.tool_choice).toBe("none")
      expect(turnRequests()).toEqual([])

      await act(async () => {
        realtime.finishResponse("resp_opening")
      })

      await waitFor(() =>
        expect(turnRequests()).toEqual(["¿Cuáles son los horarios de atención?"]),
      )
      expect(realtime.transport.updateSessionConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          audio: expect.objectContaining({
            input: expect.objectContaining({
              turnDetection: expect.objectContaining({ interruptResponse: true }),
            }),
          }),
        }),
      )
      await waitFor(() => expect(realtime.responseRequests()).toHaveLength(2))
      expect(realtime.responseRequests()[1].response?.instructions).toContain(
        '"intent":"CLARIFY"',
      )
    })

    it("answers a question whose transcription landed after the speaker went quiet", async () => {
      // Session 58933d69: "quiero saber los horarios de atención" was never answered. The
      // model created its response the instant the speaker stopped, before the words had
      // been transcribed, and nothing ever came back for them.
      await connectedKiosk({ listening: true })
      openingHeard()
      answerTurn = async () => clarifyAnalysis

      await act(async () => {
        realtime.emitTransportEvent("input_audio_buffer.speech_started")
        realtime.emitTransportEvent("input_audio_buffer.speech_stopped")
      })
      expect(turnRequests()).toEqual([])

      realtime.history = [
        {
          itemId: "item-late",
          type: "message",
          role: "user",
          status: "completed",
          content: [
            { type: "input_audio", audio: null, transcript: "Quiero saber los horarios" },
          ],
        },
      ]
      await act(async () => {
        realtime.emit("history_updated", realtime.history)
      })

      await waitFor(() => expect(turnRequests()).toEqual(["Quiero saber los horarios"]))
      await waitFor(() => expect(realtime.responseRequests()).toHaveLength(2))
      // Fast enough that no filler was said in front of the answer.
      expect(
        realtime.responseRequests().some((request) =>
          request.response?.instructions?.includes("Un momento"),
        ),
      ).toBe(false)
    })

    it("joins a lone word with the rest of the sentence instead of sending it alone", async () => {
      // Session f7c2c32e: a lone "Quiero" went to the bank as a whole request.
      await connectedKiosk({ listening: true })
      openingHeard()
      answerTurn = async () => clarifyAnalysis

      await say("item-1", "Quiero")
      expect(turnRequests()).toEqual([])
      await say("item-2", "bloquear mi tarjeta")

      await waitFor(() => expect(turnRequests()).toEqual(["Quiero bloquear mi tarjeta"]))
    })

    it("still sends a lone word if nothing follows it", async () => {
      await connectedKiosk({ listening: true })
      openingHeard()
      answerTurn = async () => clarifyAnalysis

      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
      try {
        await say("item-1", "Quiero")
        expect(turnRequests()).toEqual([])
        await act(async () => {
          vi.advanceTimersByTime(2_500)
        })
      } finally {
        vi.useRealTimers()
      }
      await waitFor(() => expect(turnRequests()).toEqual(["Quiero"]))
    })

    it("says one fixed line while the bank is slow, then the answer", async () => {
      await connectedKiosk({ listening: true })
      openingHeard()
      let releaseTurn: (value: unknown) => void = () => {}
      answerTurn = () => new Promise((resolve) => (releaseTurn = resolve))

      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] })
      try {
        await say("item-1", "Quiero bloquear mi tarjeta")
        await act(async () => {
          vi.advanceTimersByTime(1_500)
        })
      } finally {
        vi.useRealTimers()
      }

      const filler = realtime.responseRequests()[1]
      expect(filler.response?.instructions).toContain('"Un momento, por favor."')

      await act(async () => {
        releaseTurn(clarifyAnalysis)
      })
      // The answer waits for the filler to finish rather than talking over it.
      expect(realtime.responseRequests()).toHaveLength(2)
      act(() => realtime.finishResponse("resp_filler"))
      await waitFor(() => expect(realtime.responseRequests()).toHaveLength(3))
      expect(realtime.responseRequests()[2].response?.instructions).toContain(
        '"intent":"CLARIFY"',
      )
    })

    it("asks for nothing when the turn has nothing to say", async () => {
      // Session 2791c387 opened with "No hay nada nuevo que procesar, así que seguimos
      // conversando con calma": the model reading an idle tool result's guidance aloud.
      // Words spoken while the CI field is open have nothing to say -- and no response.
      await connectedKiosk()
      openingHeard()
      const before = realtime.responseRequests().length

      await say("item-1", "Ya lo estoy escribiendo")
      await act(async () => {})

      expect(turnRequests()).toEqual([])
      expect(realtime.responseRequests()).toHaveLength(before)
    })
  })

  it("cuts off the obsolete CI prompt and speaks the closing exactly once", async () => {
    const kiosk = await connectedKiosk()
    openingHeard()
    const before = realtime.responseRequests().length
    realtime.mute.mockClear()

    // The model is mid-sentence on "escribe tu CI en el campo protegido..." when the CI
    // lands. That sentence is obsolete; letting it finish and queueing the closing behind
    // it is what a fast typist heard as two unrelated turns in a row.
    act(() => realtime.emitTransportEvent("response.created", "resp_ci"))
    await act(async () => {
      await kiosk.submitIdentification("6735666")
    })

    expect(realtime.interrupt).toHaveBeenCalledTimes(1)
    const closing = realtime.responseRequests().slice(before)
    expect(closing).toHaveLength(1)
    // The outcome reaches the model the only way business data is allowed to: the
    // backend's own SpeechPlan, as data. On 2026-09-01 a model told to "say how this ends"
    // never told the customer their ticket number.
    expect(closing[0].response?.instructions).toContain('"ticket":"42"')
    expect(closing[0].response?.instructions).toContain('"verbatim":["María Torres"]')

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
    // The client already refused to *show* a superseded answer. It used to hand the same
    // response to the model anyway, so it read out an answer to a question the person had
    // already replaced.
    const kiosk = await connectedKiosk({ listening: true })
    openingHeard()
    const connection = realtime
    const before = connection.responseRequests().length
    let releaseTurn: (value: unknown) => void = () => {}
    answerTurn = () => new Promise((resolve) => (releaseTurn = resolve))

    await say("item-1", "¿Cuáles son los horarios?")
    // The conversation moves on while the backend is still answering.
    await act(async () => {
      await kiosk.reset()
    })
    await act(async () => {
      releaseTurn(automaticAnswer)
    })

    expect(connection.responseRequests()).toHaveLength(before)
  })

  it("keeps listening after a decline the session recovers from", async () => {
    // Session 2791c387: a bystander's "prototipo bueno la presentación sería" was declined
    // and the decline closed the microphone on the customer standing at the kiosk.
    await connectedKiosk({ listening: true })
    openingHeard()
    const declined = {
      requirement_id: "requirement-declined",
      status: "DECLINED",
      next_action: "DECLINE",
      customer_summary: "Necesitas orientación sobre una consulta bancaria.",
      speech_text: "En este kiosco solo puedo ayudarte con...",
      speech_plan: {
        intent: "DECLINE",
        facts: {},
        verbatim: [],
        guidance: "Dile que eso no lo atiendes.",
        fallback_text: "En este kiosco solo puedo ayudarte con...",
      },
      conversation_can_continue: true,
    }
    answerTurn = async () => declined
    realtime.mute.mockClear()

    await say("item-1", "prototipo bueno la presentación sería")
    await waitFor(() => expect(latestKiosk.analysis?.next_action).toBe("DECLINE"))
    expect(realtime.mute).not.toHaveBeenCalledWith(true)
    expect(latestKiosk.completionSeconds).toBeNull()

    answerTurn = async () => ({
      ...declined,
      requirement_id: "requirement-next",
      status: "AWAITING_CONFIRMATION",
      next_action: "CONFIRM",
    })
    await say("item-2", "Quiero bloquear mi tarjeta")

    await waitFor(() => expect(latestKiosk.analysis?.next_action).toBe("CONFIRM"))
    expect(turnRequests()).toEqual([
      "prototipo bueno la presentación sería",
      "Quiero bloquear mi tarjeta",
    ])
  })

  describe("customer-paused listening", () => {
    async function pause(paused: boolean) {
      await act(async () => {
        latestKiosk.setListeningPaused(paused)
      })
    }

    async function answeredAutomatically() {
      await connectedKiosk({ listening: true })
      openingHeard()
      answerTurn = async () => automaticAnswer
      await say("item-auto", "¿Cuál es el horario?")
      await waitFor(() => expect(latestKiosk.result?.resolution_type).toBe("AUTOMATIC"))
      // The answer is spoken and over; what is left is the follow-up window.
      await waitFor(() => expect(realtime.responseRequests()).toHaveLength(2))
      act(() => realtime.finishResponse("resp_answer"))
      expect(latestKiosk.listeningControlAvailable).toBe(true)
    }

    it("closes the microphone when the customer pauses", async () => {
      await connectedKiosk({ listening: true })
      expect(latestKiosk.listeningControlAvailable).toBe(true)
      realtime.mute.mockClear()

      await pause(true)

      expect(realtime.mute).toHaveBeenCalledWith(true)
      expect(latestKiosk.listeningPaused).toBe(true)
      expect(latestKiosk.voiceState).toBe("muted")
    })

    it("keeps a paused microphone closed across business state changes", async () => {
      // The mic policy reopens the microphone on every state change that allows it. A pause
      // that did not survive the next one would leave the customer believing the kiosk had
      // stopped listening while it was still taking their words.
      await connectedKiosk({ listening: true })
      openingHeard()
      await pause(true)
      realtime.mute.mockClear()

      // Words that were already on their way when the customer paused still get answered.
      answerTurn = async () => clarifyAnalysis
      await say("item-1", "Quiero bloquear mi tarjeta")
      await waitFor(() => expect(latestKiosk.analysis?.next_action).toBe("CLARIFY"))
      await act(async () => {})

      expect(realtime.mute).not.toHaveBeenCalledWith(false)
      expect(realtime.muted).toBe(true)
      expect(latestKiosk.voiceState).toBe("muted")
    })

    it("opens the microphone again when the customer resumes", async () => {
      await connectedKiosk({ listening: true })
      await pause(true)
      realtime.mute.mockClear()

      await pause(false)

      expect(realtime.mute).toHaveBeenCalledWith(false)
      expect(latestKiosk.listeningPaused).toBe(false)
      expect(latestKiosk.voiceState).toBe("listening")
    })

    it("cannot open the microphone while the CI field is open", async () => {
      await connectedKiosk()
      expect(latestKiosk.listeningControlAvailable).toBe(false)
      realtime.mute.mockClear()

      await pause(true)
      await pause(false)

      expect(realtime.mute).not.toHaveBeenCalled()
      expect(realtime.muted).toBe(true)
      expect(latestKiosk.listeningPaused).toBe(false)
    })

    it("starts a new connection listening", async () => {
      await connectedKiosk({ listening: true })
      await pause(true)

      await act(async () => {
        await latestKiosk.retryVoice()
      })

      expect(latestKiosk.listeningPaused).toBe(false)
      expect(latestKiosk.voiceState).toBe("listening")
    })

    it("gives a paused follow-up a longer window, and the usual one once resumed", async () => {
      await answeredAutomatically()

      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
      try {
        act(() => realtime.emitTransportEvent("output_audio_buffer.stopped"))
        await pause(true)

        // Well past the usual 20 s, the paused customer still has the kiosk.
        await act(async () => {
          vi.advanceTimersByTime(60_000)
        })
        expect(latestKiosk.completionSeconds).toBeNull()

        // Resuming puts the usual window back, counted from now.
        await pause(false)
        await act(async () => {
          vi.advanceTimersByTime(19_000)
        })
        expect(latestKiosk.completionSeconds).toBeNull()
        await act(async () => {
          vi.advanceTimersByTime(1_000)
        })
        expect(latestKiosk.completionSeconds).not.toBeNull()
      } finally {
        vi.useRealTimers()
      }
    })

    it("frees a paused kiosk whose customer walked away", async () => {
      await answeredAutomatically()

      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] })
      try {
        await pause(true)
        // Armed while paused: here the kiosk only stops speaking after the pause.
        act(() => realtime.emitTransportEvent("output_audio_buffer.stopped"))

        await act(async () => {
          vi.advanceTimersByTime(119_000)
        })
        expect(latestKiosk.completionSeconds).toBeNull()
        await act(async () => {
          vi.advanceTimersByTime(1_000)
        })
        expect(latestKiosk.voiceState).toBe("closed")
        expect(latestKiosk.completionSeconds).not.toBeNull()
      } finally {
        vi.useRealTimers()
      }
    })
  })
})
