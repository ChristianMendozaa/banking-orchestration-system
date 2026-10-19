// @module-tag functional
// @module-tag integration
// @module-tag regression

import { describe, expect, it, vi } from "vitest"

import {
  OUTAGE_GUIDANCE,
  SpeechFloor,
  analysisSpeechData,
  captionsFromHistory,
  captionsFromStoredConversation,
  correctedRequest,
  explicitConfirmation,
  fillerInstructions,
  flowSpeechData,
  greetingInstructions,
  isBenignRealtimeError,
  isConversationClose,
  isSessionStateConflict,
  isSpeechFragment,
  isTerminalFlowResult,
  mergeConversationCaptions,
  microphoneShouldBeOpen,
  missingVerbatim,
  realtimeVoiceSessionConfig,
  selectAuthoritativeTranscript,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  speechPlanData,
  turnInstructions,
  turnResultIsSilent,
  turnSpeechData,
} from "../lib/kiosk-realtime"
import { ApiError } from "../lib/api"
import { createKioskRealtimeAgent } from "../lib/kiosk-realtime-agent"
import type { FlowResult, TurnAnalysis } from "../lib/types"

const analysis: TurnAnalysis = {
  requirement_id: "requirement-1",
  status: "AWAITING_CONFIRMATION",
  summary: "Reporte de fraude en tarjeta.",
  customer_summary: "Necesitas reportar un fraude en tu tarjeta.",
  category: "REPORTE_FRAUDE",
  priority: "CRITICO",
  consultation_level: "SENSIBLE",
  confidence: 0.99,
  intent_status: "CONFIRMED",
  confirmation_kind: "INTENT",
  clarification_outcome: "NOT_APPLICABLE",
  clarification_question: null,
  pii_types: [],
  next_action: "CONFIRM",
  speech_text: "¿Me confirmas si necesitas reportar un fraude en tu tarjeta?",
  speech_plan: {
    intent: "CONFIRM",
    facts: { entendido: "Necesitas reportar un fraude en tu tarjeta." },
    verbatim: [],
    guidance: "Confirma en una pregunta breve y natural que entendiste eso.",
    fallback_text: "¿Me confirmas si necesitas reportar un fraude en tu tarjeta?",
  },
  conversation_can_continue: false,
}

const completed: FlowResult = {
  session_id: "session-1",
  requirement_id: "requirement-1",
  status: "ASSIGNED",
  next_action: "COMPLETE",
  customer_summary: analysis.customer_summary,
  priority: analysis.priority,
  identification_status: "IDENTIFICADO",
  resolution_type: "HUMAN",
  ticket: {
    id: "ticket-1",
    number: 4,
    status: "PENDIENTE",
    estimated_wait_minutes: 3,
  },
  executive: null,
  response: null,
  speech_text: "Tu ticket es 4. Dirígete a Ventanilla 3 con María Torres.",
  speech_plan: {
    intent: "HANDOFF",
    facts: { ticket: "4", ventanilla: "Ventanilla 3", ejecutivo: "María Torres" },
    verbatim: ["María Torres"],
    guidance: "Dale el ticket, la ventanilla y el nombre exactamente como aparecen.",
    fallback_text: "Tu ticket es 4. Dirígete a Ventanilla 3 con María Torres.",
  },
  tracking_information: null,
  grounding_status: "NOT_APPLICABLE",
  intent_status: "CONFIRMED",
  citations: [],
  conversation_can_continue: false,
  remaining_turns: 0,
}

describe("explicitConfirmation", () => {
  it.each(["sí", "Sí, es correcto", "confirmo", "está bien", "de acuerdo"])(
    "acepta una confirmación positiva explícita: %s",
    (value) => {
      expect(explicitConfirmation(value)).toBe(true)
    },
  )

  it.each(["no", "No, es incorrecto", "quiero corregir", "está equivocado"])(
    "acepta una corrección explícita: %s",
    (value) => {
      expect(explicitConfirmation(value)).toBe(false)
    },
  )

  it.each([
    "quizás",
    "puede ser",
    "continúe",
    "sí, pero no",
    // Folding diacritics collapsed the affirmation "sí" onto the conditional conjunction
    // "si", so this matched positive at index 0 and negative at index 3 -- a banking
    // requirement confirmed by the sentence questioning it.
    "si no es correcto, corrígelo",
    // Answering a yes/no question with a question of your own is not answering it. This
    // matched `claro` and confirmed the requirement.
    "Claro, ¿qué entendiste?",
    // A yes to something else entirely. It carried a positive cue and no negative one.
    "sí, pero quiero consultar primero",
  ])("rechaza respuestas ambiguas: %s", (value) => {
    expect(explicitConfirmation(value)).toBeNull()
  })
})

describe("correctedRequest", () => {
  const captured = {
    ...completed,
    next_action: "CAPTURE",
  } as unknown as FlowResult

  it("carries the request a rejection named in place of the one it rejected", () => {
    expect(
      correctedRequest({
        ...captured,
        corrected_request: "Quiero conocer los requisitos para un crédito",
      } as FlowResult),
    ).toBe("Quiero conocer los requisitos para un crédito")
  })

  it("has nothing to carry when the rejection did not say what it wanted instead", () => {
    expect(correctedRequest(captured)).toBeNull()
  })

  it("is read defensively, so an older backend simply has no correction", () => {
    // The field is additive; a client talking to a deployment without it must not fail.
    expect(correctedRequest({ ...captured, corrected_request: undefined } as FlowResult)).toBeNull()
  })
})

describe("captionsFromHistory", () => {
  it("shows only user and assistant messages, no internal events", () => {
    const captions = captionsFromHistory([
      {
        itemId: "user-audio",
        type: "message",
        role: "user",
        status: "completed",
        content: [{ type: "input_audio", audio: null, transcript: "Necesito ayuda" }],
      },
      {
        itemId: "internal",
        type: "message",
        role: "system",
        content: [{ type: "input_text", text: "Instrucciones internas" }],
      },
      {
        itemId: "assistant",
        type: "message",
        role: "assistant",
        status: "completed",
        content: [
          {
            type: "output_audio",
            audio: null,
            transcript: "¿En qué puedo ayudarte?",
          },
        ],
      },
    ])

    expect(captions).toEqual([
      {
        id: "user-audio",
        role: "user",
        text: "Necesito ayuda",
        completed: true,
      },
      {
        id: "assistant",
        role: "assistant",
        text: "¿En qué puedo ayudarte?",
        completed: true,
      },
    ])
  })
})

describe("persistent conversation history", () => {
  it("keeps every stored message when a reconnect supplies only newer live history", () => {
    const stored = captionsFromStoredConversation(
      Array.from({ length: 8 }, (_, index) => ({
        item_id: `stored-${index}`,
        role: index % 2 === 0 ? ("CUSTOMER" as const) : ("ASSISTANT" as const),
        text: `Mensaje ${index}`,
        created_at: `2026-08-31T10:00:0${index}Z`,
      })),
    )
    const merged = mergeConversationCaptions(stored, [
      {
        id: "live-9",
        role: "user",
        text: "Quiero sacar un crédito ahora",
        completed: true,
      },
    ])

    expect(merged).toHaveLength(9)
    expect(merged.map((caption) => caption.id)).toEqual([
      ...stored.map((caption) => caption.id),
      "live-9",
    ])
  })

  it("updates a persisted item from live history without duplicating it", () => {
    const stored = captionsFromStoredConversation([
      {
        item_id: "same",
        role: "CUSTOMER",
        text: "Quiero sacar un crédito",
        created_at: "2026-08-31T10:00:00Z",
      },
    ])
    const merged = mergeConversationCaptions(stored, [
      { id: "same", role: "user", text: "Quiero sacar un crédito ahora", completed: true },
    ])

    expect(merged).toHaveLength(1)
    expect(merged[0].text).toBe("Quiero sacar un crédito ahora")
  })
})

describe("realtime session controls", () => {
  it.each(["No, gracias", "Eso es todo", "Nada más, gracias"])(
    "recognizes a complete social close: %s",
    (value) => expect(isConversationClose(value)).toBe(true),
  )

  it.each(["No puedo abrir la cuenta", "Gracias, quiero un crédito", "Necesito algo más"])(
    "does not mistake a banking turn for a close: %s",
    (value) => expect(isConversationClose(value)).toBe(false),
  )

  it("preserves backend audio settings whenever interruptions are toggled", () => {
    const audioInput = {
      noise_reduction: { type: "near_field" },
      transcription: { model: "gpt-realtime-whisper", language: "es" },
      turn_detection: {
        type: "semantic_vad",
        eagerness: "low" as const,
        create_response: false,
        interrupt_response: true,
      },
    }
    const opening = realtimeVoiceSessionConfig(audioInput, "marin", {
      interruptResponse: false,
    })
    const conversation = realtimeVoiceSessionConfig(audioInput, "marin", {
      interruptResponse: true,
    })

    expect(opening.audio.input.transcription).toEqual(audioInput.transcription)
    expect(opening.audio.input.noiseReduction).toEqual(audioInput.noise_reduction)
    // The backend's choice that the session never answers by itself survives every update.
    expect(opening.audio.input.turnDetection).toMatchObject({
      type: "semantic_vad",
      eagerness: "low",
      create_response: false,
      interruptResponse: false,
    })
    expect(conversation.audio.input.turnDetection).toMatchObject({
      create_response: false,
      interruptResponse: true,
    })
    expect(conversation).not.toHaveProperty("toolChoice")
  })
})

describe("selectAuthoritativeTranscript", () => {
  const caption = (
    id: string,
    role: "user" | "assistant",
    text: string,
    completed = true,
  ) => ({ id, role, text, completed })

  it("takes the customer's transcribed words and ignores the assistant's", () => {
    const selection = selectAuthoritativeTranscript(
      [
        caption("a", "assistant", "¿En qué puedo ayudarte?"),
        caption("b", "user", "Quiero reportar el robo de mi tarjeta de débito."),
      ],
      new Set(),
    )

    expect(selection).toEqual({
      text: "Quiero reportar el robo de mi tarjeta de débito.",
      itemIds: ["b"],
    })
  })

  it("joins a turn that arrived split across two audio items", () => {
    const selection = selectAuthoritativeTranscript(
      [
        caption("a", "user", "Quiero reportar"),
        caption("b", "user", "el robo de mi tarjeta."),
      ],
      new Set(),
    )

    expect(selection?.text).toBe("Quiero reportar el robo de mi tarjeta.")
    expect(selection?.itemIds).toEqual(["a", "b"])
  })

  it("never re-sends a transcript that a previous turn already consumed", () => {
    const captions = [caption("a", "user", "Quiero reportar el robo.")]

    expect(selectAuthoritativeTranscript(captions, new Set(["a"]))).toBeNull()
  })

  it("waits for a transcription that is still in progress", () => {
    const selection = selectAuthoritativeTranscript(
      [caption("a", "user", "Quiero repor", false)],
      new Set(),
    )

    expect(selection).toBeNull()
  })
})

describe("missingVerbatim", () => {
  // Facts the backend decided are the model's to present but not to reword. This is the
  // only constraint left on its wording, and it checks what it can honestly check: text.
  it("accepts a fact wrapped in the model's own words", () => {
    expect(
      missingVerbatim(
        "Listo, te derivo con María Torres, en Ventanilla 3, ella te ayuda con eso.",
        ["Ventanilla 3", "María Torres"],
      ),
    ).toEqual([])
  })

  it("tolerates accent and casing differences the transcription introduces", () => {
    expect(
      missingVerbatim("dirigete a ventanilla 3 con maria torres", [
        "Ventanilla 3",
        "María Torres",
      ]),
    ).toEqual([])
  })

  it("reports a fact the model paraphrased away", () => {
    expect(
      missingVerbatim("Te derivo con un ejecutivo que te va a ayudar.", [
        "María Torres",
      ]),
    ).toEqual(["María Torres"])
  })

  it("reports everything measurable when nothing was said at all", () => {
    expect(missingVerbatim("", ["María Torres"])).toEqual(["María Torres"])
  })

  it("never flags an entry speech cannot render as written", () => {
    // "Ventanilla 3" is said as "ventanilla tres" and 42 as "cuarenta y dos". Measuring
    // those was how a correct reading became a failure -- and the kiosk answered failures
    // by making the model recite the fragment, which is what customers heard trailing
    // their ticket number.
    expect(
      missingVerbatim("Dirígete a ventanilla tres con María Torres.", [
        "Ventanilla 3",
        "María Torres",
      ]),
    ).toEqual([])
    expect(missingVerbatim("", ["Ventanilla 3", "42"])).toEqual([])
  })
})

const agentOptions = {
  instructions: "Eres la asistente virtual de un kiosco del banco.",
  voice: "marin",
}

describe("createKioskRealtimeAgent", () => {
  it("takes its persona from the client secret the backend minted", () => {
    // The Agents SDK sends these as the session instructions on connect, so a second copy
    // written in the frontend would be the one that actually governed the conversation.
    const agent = createKioskRealtimeAgent(agentOptions)

    expect(agent.voice).toBe("marin")
    expect(agent.instructions).toBe(agentOptions.instructions)
  })

  it("has no tools to decide with", () => {
    // On 2026-10-14 the model called `procesar_turno` on the noise in the room before it had
    // greeted anyone, and read "no hay nada nuevo que procesar" aloud. The application owns
    // the turn now; the model has nothing to call.
    expect(createKioskRealtimeAgent(agentOptions).tools).toEqual([])
  })
})

describe("turnInstructions", () => {
  const persona = agentOptions.instructions

  it("repeats the persona and hands over the turn as data, never a sentence to read", () => {
    // A `response.create` that carries instructions replaces the session's for that
    // response, so the persona has to travel with every one.
    const instructions = turnInstructions(persona, { kind: "analysis", response: analysis })

    expect(instructions).not.toBeNull()
    expect(instructions!.startsWith(persona)).toBe(true)
    expect(instructions).toContain("ESTE TURNO")
    const data = JSON.parse(instructions!.slice(instructions!.indexOf("{")))
    expect(data).toMatchObject({
      ok: true,
      next_action: "CONFIRM",
      intent: "CONFIRM",
      guidance: analysis.speech_plan.guidance,
      facts: analysis.speech_plan.facts,
      verbatim: [],
    })
    expect(instructions).not.toContain(analysis.speech_text)
  })

  it.each(["awaiting_identification", "settled", "superseded", "noop"] as const)(
    "asks for no response at all on a %s result",
    (kind) => {
      // The guidance these used to carry ("no hay nada nuevo que procesar...") was itself
      // read aloud to a customer. Not asking is the only silence that cannot be broken.
      expect(turnInstructions(persona, { kind })).toBeNull()
    },
  )

  it("apologises for a real outage and only for that", () => {
    const instructions = turnInstructions(persona, { kind: "retry", guidance: "" })
    expect(instructions).toContain(OUTAGE_GUIDANCE)
    expect(instructions).toContain('"ok":false')
  })

  it("speaks a form-submitted handoff from its own facts", () => {
    // Recorded 2026-09-01, session b7844a53: a customer assigned ticket 1 at Ventanilla 4
    // with Roberto Torrez was told the next step "depends on internal confirmation",
    // because the outcome of typing the CI never reached the model. It is spoken from the
    // backend's own SpeechPlan now, like any other turn.
    const handoff: FlowResult = {
      ...completed,
      speech_plan: {
        ...completed.speech_plan,
        facts: { ticket: "1", ventanilla: "Ventanilla 4", ejecutivo: "Roberto Torrez" },
        verbatim: ["Roberto Torrez"],
      },
    }
    const instructions = turnInstructions(persona, { kind: "flow", response: handoff })

    expect(instructions).toContain('"ventanilla":"Ventanilla 4"')
    expect(instructions).toContain('"verbatim":["Roberto Torrez"]')
  })

  it("greets naming only what the kiosk attends, and fills a wait with one fixed line", () => {
    expect(greetingInstructions(persona)).toContain("LO QUE ATIENDES")
    // The model's own fillers were "Claro, déjame verificar la petición por un momento"
    // before every single lookup.
    expect(fillerInstructions(persona)).toContain("Un momento, por favor.")
  })
})

describe("isSpeechFragment", () => {
  it.each(["Quiero", "Eh...", "Bueno"])("holds the front of an unfinished sentence: %s", (value) => {
    // On 2026-10-14 a lone "Quiero" was sent to the bank as a whole request.
    expect(isSpeechFragment(value)).toBe(true)
  })

  it.each(["Sí", "No", "Claro", "Gracias", "Quiero bloquear mi tarjeta"])(
    "sends a complete reply straight away: %s",
    (value) => expect(isSpeechFragment(value)).toBe(false),
  )
})

describe("turn speech data", () => {
  it("makes each grounded answer authoritative without carrying the previous answer forward", () => {
    const hours =
      "La Sucursal Centro atiende de lunes a viernes de 08:30 a 19:00 y sábados de 09:00 a 13:00."
    const credit = "Para solicitar un crédito de consumo debes ser mayor de 18 años."
    const automatic = (requirementId: string, answer: string): FlowResult => ({
      ...completed,
      requirement_id: requirementId,
      status: "RESOLVED_AUTOMATIC",
      resolution_type: "AUTOMATIC",
      ticket: null,
      response: answer,
      speech_text: answer,
      speech_plan: {
        intent: "ANSWER",
        facts: { respuesta_fundamentada: answer },
        verbatim: [answer],
        guidance: "Di la respuesta aprobada completa.",
        fallback_text: answer,
      },
      grounding_status: "GROUNDED",
      conversation_can_continue: true,
      remaining_turns: 7,
    })

    const hoursOutput = flowSpeechData(automatic("hours", hours))
    const creditOutput = flowSpeechData(automatic("credit", credit))

    expect(hoursOutput).toMatchObject({
      intent: "ANSWER",
      grounded_answer: hours,
      facts: { respuesta_fundamentada: hours },
    })
    expect(creditOutput).toMatchObject({
      intent: "ANSWER",
      grounded_answer: credit,
      facts: { respuesta_fundamentada: credit },
    })
    expect(JSON.stringify(creditOutput)).not.toContain(hours)
  })

  it("routes a COMPLETE analysis (GENERAL, no confirmation step) through the flow shape", () => {
    const autoResolved: TurnAnalysis = {
      ...analysis,
      consultation_level: "GENERAL",
      next_action: "COMPLETE",
      speech_text: completed.speech_text,
      speech_plan: completed.speech_plan,
      result: completed,
    }
    expect(analysisSpeechData(autoResolved)).toEqual(flowSpeechData(completed))
  })

  it("carries the plan's own fields and never the written fallback", () => {
    const output = speechPlanData(completed.speech_plan, { next_action: "COMPLETE" })
    expect(output).toEqual({
      ok: true,
      next_action: "COMPLETE",
      intent: "HANDOFF",
      guidance: completed.speech_plan.guidance,
      facts: completed.speech_plan.facts,
      verbatim: completed.speech_plan.verbatim,
    })
    expect(output).not.toHaveProperty("fallback_text")
  })

  it("still closes the session on a human handoff but not on an automatic answer", () => {
    // An answer the kiosk produced by itself leaves the customer standing there, and the
    // backend now opens a second case for a follow-up question, so closing the session on
    // COMPLETE would hang up on someone mid-conversation.
    expect(isTerminalFlowResult(completed)).toBe(true)
    expect(
      isTerminalFlowResult({
        ...completed,
        resolution_type: "AUTOMATIC",
        conversation_can_continue: true,
      }),
    ).toBe(false)
    expect(
      isTerminalFlowResult({
        ...completed,
        resolution_type: "AUTOMATIC",
        conversation_can_continue: false,
      }),
    ).toBe(true)
  })
})

describe("business response ordering", () => {
  it("does not let a delayed analysis erase identification or closure", () => {
    const identify = {
      ...completed,
      next_action: "IDENTIFY" as const,
      status: "AWAITING_IDENTIFICATION" as const,
      ticket: null,
    }

    expect(
      shouldApplyAnalysisResponse(
        { analysis, result: identify },
        analysis,
        null,
        true,
      ),
    ).toBe(false)
    expect(
      shouldApplyAnalysisResponse(
        { analysis, result: completed },
        analysis,
        null,
        true,
      ),
    ).toBe(false)
  })

  it("accepts a clarification's advance if only its initial phase was reconciled", () => {
    const clarified = { ...analysis, requirement_id: "requirement-2" }
    expect(
      shouldApplyAnalysisResponse(
        { analysis, result: null },
        clarified,
        analysis.requirement_id,
        true,
      ),
    ).toBe(true)
  })

  it("does not revive a request that was already rejected", () => {
    const capture = {
      ...completed,
      next_action: "CAPTURE" as const,
      status: "LISTENING" as const,
      ticket: null,
    }
    expect(
      shouldApplyAnalysisResponse(
        { analysis: null, result: capture },
        analysis,
        analysis.requirement_id,
        true,
      ),
    ).toBe(false)
    expect(
      shouldApplyAnalysisResponse(
        { analysis: null, result: capture },
        { ...analysis, requirement_id: "requirement-2" },
        null,
        true,
      ),
    ).toBe(true)
  })

  it("lets a follow-up question replace an automatic answer", () => {
    // A different requirement_id normally means a stale response arriving late. After an
    // automatic answer it means the opposite: the customer asked something else, and that
    // second requirement is the current one.
    const answered = {
      ...completed,
      resolution_type: "AUTOMATIC" as const,
      conversation_can_continue: true,
      ticket: null,
    }
    const followUp = {
      ...answered,
      requirement_id: "requirement-2",
      ticket: null,
    }
    expect(
      shouldApplyFlowResponse(
        { analysis: null, result: answered },
        followUp,
        followUp.requirement_id,
        true,
      ),
    ).toBe(true)
    // ...but a stale one after a human handoff is still discarded.
    expect(
      shouldApplyFlowResponse(
        { analysis: null, result: completed },
        {
          ...completed,
          requirement_id: "requirement-2",
          ticket: { ...completed.ticket!, id: "ticket-2", number: 5 },
        },
        "requirement-2",
        true,
      ),
    ).toBe(false)
  })

  it("does not let a delayed IDENTIFY replace a COMPLETE ticket", () => {
    const identify = {
      ...completed,
      next_action: "IDENTIFY" as const,
      status: "AWAITING_IDENTIFICATION" as const,
      ticket: null,
    }
    expect(
      shouldApplyFlowResponse(
        { analysis, result: completed },
        identify,
        analysis.requirement_id,
        true,
      ),
    ).toBe(false)
  })
})

describe("silent and failed turns", () => {
  // Three states in which there is genuinely nothing to say. Every one of them used to reach
  // the customer either as an apology for a failure that never happened or as the model
  // reading its own instructions aloud.
  it.each(["awaiting_identification", "settled", "noop"] as const)(
    "has no speech data for %s",
    (kind) => expect(turnSpeechData({ kind })).toBeNull(),
  )

  it("keeps a real outage distinguishable from a state disagreement", () => {
    expect(isSessionStateConflict(new ApiError(409, { code: "INVALID_SESSION_STATE" }))).toBe(
      true,
    )
    expect(isSessionStateConflict(new ApiError(409, { code: "INVALID_CLARIFICATION" }))).toBe(
      true,
    )
    expect(isSessionStateConflict(new ApiError(503, { code: "REALTIME_UNAVAILABLE" }))).toBe(
      false,
    )
    expect(isSessionStateConflict(new Error("sin red"))).toBe(false)
    expect(turnSpeechData({ kind: "retry", guidance: "" })).toMatchObject({
      ok: false,
      guidance: OUTAGE_GUIDANCE,
    })
  })
})

describe("microphoneShouldBeOpen", () => {
  it("closes the microphone for the credential window and for a finished case", () => {
    expect(
      microphoneShouldBeOpen({
        analysis: null,
        result: { ...completed, next_action: "IDENTIFY" },
      }),
    ).toBe(false)
    expect(microphoneShouldBeOpen({ analysis: null, result: completed })).toBe(false)
    expect(
      microphoneShouldBeOpen({
        analysis: { ...analysis, next_action: "DECLINE" },
        result: null,
      }),
    ).toBe(false)
  })

  // On 2026-10-14 a bystander's sentence was declined and the decline closed the microphone
  // on the customer standing at the kiosk.
  it("keeps it open after a decline the session recovers from", () => {
    expect(
      microphoneShouldBeOpen({
        analysis: { ...analysis, next_action: "DECLINE", conversation_can_continue: true },
        result: null,
      }),
    ).toBe(true)
  })

  it("leaves it open everywhere else, including mid-confirmation", () => {
    expect(microphoneShouldBeOpen({ analysis, result: null })).toBe(true)
    expect(microphoneShouldBeOpen({ analysis: null, result: null })).toBe(true)
    expect(
      microphoneShouldBeOpen({
        analysis: null,
        result: {
          ...completed,
          resolution_type: "AUTOMATIC",
          conversation_can_continue: true,
        },
      }),
    ).toBe(true)
  })
})

describe("SpeechFloor", () => {
  const transport = () => ({ speak: vi.fn(), interrupt: vi.fn() })

  it("speaks immediately when nothing else is speaking", () => {
    const wire = transport()
    new SpeechFloor(wire).request("resume", () => "hola")
    expect(wire.speak).toHaveBeenCalledWith("hola")
  })

  it("holds an injection until the current response is done", () => {
    // The SDK's sequencer queues a `response.create` that arrives mid-response rather than
    // dropping it, so an unarbitrated injection always came out eventually -- as a stray
    // sentence trailing the previous one.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    floor.request("resume", () => "hola")
    expect(wire.speak).not.toHaveBeenCalled()

    floor.noteResponseDone()
    expect(wire.speak).toHaveBeenCalledWith("hola")
  })

  it("drops a held injection whose state has moved on", () => {
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    let stillRelevant = true
    floor.request("resume", () => (stillRelevant ? "hola" : null))
    stillRelevant = false
    floor.noteResponseDone()
    expect(wire.speak).not.toHaveBeenCalled()
  })

  it("coalesces repeated requests of the same kind, last one wins", () => {
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    floor.request("identification_close", () => "primero")
    floor.request("identification_close", () => "después")
    floor.noteResponseDone()
    expect(wire.speak).toHaveBeenCalledTimes(1)
    expect(wire.speak).toHaveBeenCalledWith("después")
  })

  it("cuts off a sentence the customer has already made obsolete", () => {
    // Typing the CI while the kiosk is still reading out "escribe tu CI en el campo
    // protegido". Letting that finish and queueing the closing behind it is what a fast
    // typist heard as two unrelated turns back to back.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    floor.preempt("identification_close", () => "ya quedó resuelto")

    expect(wire.interrupt).toHaveBeenCalledTimes(1)
    expect(wire.speak).toHaveBeenCalledWith("ya quedó resuelto")
  })

  it("runs a deferred closing only once the model has stopped talking", () => {
    // `response.done` means generation finished, not that the kiosk fell silent: the audio
    // it produced is still coming out of the buffer. Closing the session there tears down
    // the transport mid-sentence.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    const close = vi.fn()
    floor.noteResponseStarted()
    floor.noteAudioStarted()
    floor.whenFree(close)
    floor.noteResponseDone()
    expect(close).not.toHaveBeenCalled()

    floor.noteAudioFinished()
    expect(close).toHaveBeenCalledTimes(1)
  })

  it("frees the floor when a barge-in cuts the audio short", () => {
    // Playback interrupted mid-sentence never reports the buffer as stopped. A floor that
    // kept believing the kiosk was speaking would hold every pending message, and the
    // session itself, open forever.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    floor.noteAudioStarted()
    floor.noteResponseDone()
    expect(floor.busy).toBe(true)

    floor.noteAudioFinished()
    expect(floor.busy).toBe(false)
  })

  it("releases waiters when the connection goes away", () => {
    const wire = transport()
    const floor = new SpeechFloor(wire)
    const close = vi.fn()
    floor.noteResponseStarted()
    floor.whenFree(close)
    floor.reset()
    expect(close).toHaveBeenCalledTimes(1)
  })

  it("ignores the cancelled response's own farewell events", () => {
    // The defect this identification exists for. `response.cancel` does not stop the
    // response it cancels from reporting `response.done` and a cleared audio buffer, and
    // those arrive *after* the replacement response has started. A floor that only counted
    // "is something speaking" freed the replacement mid-sentence -- and with it every
    // `whenFree` waiter, one of which tears the session down.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    const close = vi.fn()
    floor.noteResponseStarted("resp_A")
    floor.noteAudioStarted("resp_A")

    floor.preempt("identification_close", () => "ya quedó resuelto")
    expect(wire.interrupt).toHaveBeenCalledTimes(1)
    expect(wire.speak).toHaveBeenCalledWith("ya quedó resuelto")

    // The injection is on the wire; the server acknowledges it, and only then does the
    // cancelled response finish winding down.
    floor.noteResponseStarted("resp_B")
    floor.noteAudioStarted("resp_B")
    floor.whenFree(close)
    floor.noteResponseDone("resp_A")
    floor.noteAudioFinished("resp_A")

    expect(floor.busy).toBe(true)
    expect(close).not.toHaveBeenCalled()

    floor.noteResponseDone("resp_B")
    floor.noteAudioFinished("resp_B")
    expect(close).toHaveBeenCalledTimes(1)
  })

  it("does not stay busy forever when an injection is never acknowledged", () => {
    // `conversation_already_has_active_response` is swallowed as benign, so a rejected
    // `response.create` produces no `response.created` and no `response.done`. The floor
    // used to mark itself speaking on send and wait for an event that never came.
    vi.useFakeTimers()
    try {
      const wire = transport()
      const floor = new SpeechFloor(wire)
      floor.request("resume", () => "hola")
      expect(floor.busy).toBe(true)

      vi.advanceTimersByTime(5_000)
      expect(floor.busy).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it("silences without queueing anything to say", () => {
    // What the identity-card submission needs: the instruction it invalidates has to stop
    // before the HTTP round trip, and what to say is only known afterwards.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted("resp_A")
    floor.noteAudioStarted("resp_A")

    floor.silenceNow()
    expect(wire.interrupt).toHaveBeenCalledTimes(1)
    expect(wire.speak).not.toHaveBeenCalled()
  })

  it("cancels a response that had not started yet when it is silenced", () => {
    // Submitting the identity card before the instruction's audio began. The SDK puts a
    // `response.create` on the wire the moment the instruction is requested, so at that
    // moment there is frequently nothing playing to cancel -- and without this the invalidated
    // sentence simply starts after the thing that invalidated it.
    const wire = transport()
    const floor = new SpeechFloor(wire)

    floor.silenceNow()
    floor.noteResponseStarted("resp_late")
    expect(wire.interrupt).toHaveBeenCalledTimes(1)
  })

  it("does not swallow the message the application went silent in order to say", () => {
    // `silenceNow` then, once the backend answers, `preempt`. The standing suppression is
    // about the sentence that was cancelled, not about the handover queued behind it.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted("resp_ci")
    floor.noteAudioStarted("resp_ci")

    floor.silenceNow()
    floor.noteResponseDone("resp_ci")
    floor.noteAudioFinished("resp_ci")
    floor.preempt("identification_close", () => "ya escribió su CI")

    expect(wire.speak).toHaveBeenCalledWith("ya escribió su CI")
    const interruptsBefore = wire.interrupt.mock.calls.length
    floor.noteResponseStarted("resp_handover")
    expect(wire.interrupt).toHaveBeenCalledTimes(interruptsBefore)
  })
})

describe("turnResultIsSilent", () => {
  it.each(["awaiting_identification", "settled", "superseded", "noop"] as const)(
    "has nothing to add to a %s result",
    (kind) => {
      expect(turnResultIsSilent({ kind })).toBe(true)
    },
  )
})

describe("isBenignRealtimeError", () => {
  it("ignores a lost race for the response slot", () => {
    expect(
      isBenignRealtimeError({ error: { code: "conversation_already_has_active_response" } }),
    ).toBe(true)
    expect(isBenignRealtimeError({ code: "response_cancel_not_active" })).toBe(true)
  })

  it("still surfaces everything else", () => {
    expect(isBenignRealtimeError({ error: { code: "session_expired" } })).toBe(false)
    expect(isBenignRealtimeError(new Error("data channel closed"))).toBe(false)
    expect(isBenignRealtimeError(null)).toBe(false)
  })
})
