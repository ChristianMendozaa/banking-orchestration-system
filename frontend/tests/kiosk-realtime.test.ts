// @module-tag functional
// @module-tag integration
// @module-tag regression

import { describe, expect, it, vi } from "vitest"

import {
  analysisToolOutput,
  APPLICATION_EVENT_PREFIX,
  captionsFromHistory,
  captionsFromStoredConversation,
  isTerminalFlowResult,
  isConversationClose,
  explicitConfirmation,
  flowToolOutput,
  mergeConversationCaptions,
  missingVerbatim,
  isBenignRealtimeError,
  isSessionStateConflict,
  microphoneShouldBeOpen,
  realtimeToolChoiceForTurn,
  realtimeVoiceSessionConfig,
  selectAuthoritativeTranscript,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  speechPlanToolOutput,
  turnProcessingToolOutput,
  SpeechFloor,
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

  it.each(["quizás", "puede ser", "continúe", "sí, pero no"])(
    "rechaza respuestas ambiguas: %s",
    (value) => {
      expect(explicitConfirmation(value)).toBeNull()
    },
  )
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
        role: "user",
        status: "completed",
        content: [
          {
            type: "input_text",
            text: `${APPLICATION_EVENT_PREFIX} inicia la atención`,
          },
        ],
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

describe("realtime turn controls", () => {
  it("forbids startup tools, requires processing while a turn is unspent, then permits speech", () => {
    expect(
      realtimeToolChoiceForTurn({ greeted: false, hasUnspentTranscript: false }),
    ).toBe("none")
    expect(
      realtimeToolChoiceForTurn({ greeted: true, hasUnspentTranscript: true }),
    ).toBe("required")
    expect(
      realtimeToolChoiceForTurn({ greeted: true, hasUnspentTranscript: false }),
    ).toBe("auto")
  })

  it("never forces a tool call on noise", () => {
    // `required` used to be armed by `input_audio_buffer.speech_started`, so a cough or the
    // kiosk's own audio leaking into the microphone forced the *next* response to call the
    // tool -- frequently the response that was supposed to speak the previous tool's result.
    // It found no transcript and apologised. Nothing but an actual unspent transcript arms
    // it now, and a spent one releases it before the result is spoken.
    expect(
      realtimeToolChoiceForTurn({ greeted: true, hasUnspentTranscript: false }),
    ).not.toBe("required")
  })

  it("keeps the greeting free of tools even before any audio has played", () => {
    expect(
      realtimeToolChoiceForTurn({ greeted: false, hasUnspentTranscript: true }),
    ).toBe("none")
  })

  it.each(["No, gracias", "Eso es todo", "Nada más, gracias"])(
    "recognizes a complete social close: %s",
    (value) => expect(isConversationClose(value)).toBe(true),
  )

  it.each(["No puedo abrir la cuenta", "Gracias, quiero un crédito", "Necesito algo más"])(
    "does not mistake a banking turn for a close: %s",
    (value) => expect(isConversationClose(value)).toBe(false),
  )

  it("preserves backend audio settings whenever tool choice changes", () => {
    const audioInput = {
      noise_reduction: { type: "near_field" },
      transcription: { model: "gpt-realtime-whisper", language: "es" },
      turn_detection: {
        type: "semantic_vad",
        eagerness: "auto" as const,
        create_response: true,
        interrupt_response: true,
      },
    }
    const required = realtimeVoiceSessionConfig(audioInput, "marin", "required")
    const automatic = realtimeVoiceSessionConfig(audioInput, "marin", "auto")
    const greeting = realtimeVoiceSessionConfig(audioInput, "marin", "none")

    expect(required.toolChoice).toBe("required")
    expect(automatic.toolChoice).toBe("auto")
    expect(greeting.toolChoice).toBe("none")
    expect(required.audio).toEqual(automatic.audio)
    expect(greeting.audio).toEqual(required.audio)
    expect(required.audio.input.transcription).toEqual(audioInput.transcription)
    expect(required.audio.input.turnDetection).toEqual(audioInput.turn_detection)
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

function toolNamed(
  agent: ReturnType<typeof createKioskRealtimeAgent>,
  name: string,
) {
  const found = agent.tools.find(
    (candidate) => candidate.type === "function" && candidate.name === name,
  )
  if (!found || found.type !== "function") {
    throw new Error(`No se encontró la herramienta ${name}`)
  }
  return found
}

describe("createKioskRealtimeAgent", () => {
  it("takes its persona from the client secret the backend minted", () => {
    // The Agents SDK sends these as the session instructions on connect, so a second copy
    // written in the frontend would be the one that actually governed the conversation.
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult: () => null,
        resolveSpokenText: async () => null,
        processSpokenTurn: vi.fn(),
      },
      agentOptions,
    )

    expect(agent.voice).toBe("marin")
    expect(agent.instructions).toBe(agentOptions.instructions)
    expect(agent.tools.map((item) => item.name)).toEqual(["procesar_turno"])
  })

  it("hands the model facts and guidance, never a sentence to read out", async () => {
    // The whole point of the change: a tool result is raw material for the model's own
    // wording. `speech_text` deliberately does not reach it.
    const processSpokenTurn = vi.fn().mockResolvedValue({
      kind: "analysis",
      response: analysis,
    })
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult: () => null,
        resolveSpokenText: async () => ({ text: "Me robaron la tarjeta.", commit: vi.fn() }),
        processSpokenTurn,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "procesar_turno").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-1" } } as never,
    )

    expect(processSpokenTurn).toHaveBeenCalledWith("Me robaron la tarjeta.", "call-1")
    const parsed = output
    expect(parsed).toMatchObject({
      ok: true,
      next_action: "CONFIRM",
      intent: "CONFIRM",
      guidance: analysis.speech_plan.guidance,
      facts: analysis.speech_plan.facts,
      verbatim: [],
    })
    expect(output).not.toHaveProperty("speech_text")
  })

  it("cannot classify the model's retelling, because there is nothing to retell into", async () => {
    // The production failure this design removes: the customer said "reportar el robo",
    // the model typed "portar el juego" into `fallback_transcript`, and the backend
    // classified that. The tool now takes no arguments at all.
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult: () => null,
        resolveSpokenText: async () => ({ text: "Quiero reportar el robo de mi tarjeta de débito.", commit: vi.fn() }),
        processSpokenTurn: vi.fn().mockResolvedValue({
          kind: "analysis",
          response: analysis,
        }),
      },
      agentOptions,
    )
    const analyzeTool = toolNamed(agent, "procesar_turno")

    expect(
      Object.keys(
        (analyzeTool.parameters as { properties?: Record<string, unknown> }).properties ?? {},
      ),
    ).toEqual([])
  })

  it("stays quiet, and never invents a transcript, when none landed", async () => {
    // There is no second-best transcript; inventing one is the bug this design replaced.
    // But "there is nothing to process" is not a failure either. Reporting it as one made
    // the model apologise and ask the person to repeat themselves every time it called the
    // tool without a fresh turn -- while they were typing their CI, for instance.
    const processSpokenTurn = vi.fn()
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult: () => null,
        resolveSpokenText: async () => null,
        processSpokenTurn,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "procesar_turno").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-2" } } as never,
    )

    expect(processSpokenTurn).not.toHaveBeenCalled()
    // `ok: true` is the load-bearing part: the persona treats `ok: false` as something it
    // must apologise for, and nothing here went wrong.
    expect(output).toMatchObject({ ok: true, intent: "NOOP", next_action: "NONE" })
  })

  it("passes the terminal facts through as strings the model must keep intact", async () => {
    const processSpokenTurn = vi.fn().mockResolvedValue({
      kind: "flow",
      response: completed,
    })
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult: () => null,
        resolveSpokenText: async () => ({ text: "Sí, es correcto", commit: vi.fn() }),
        processSpokenTurn,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "procesar_turno").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-3" } } as never,
    )

    expect(processSpokenTurn).toHaveBeenCalledWith("Sí, es correcto", "call-3")
    expect(output).toMatchObject({
      next_action: "COMPLETE",
      intent: "HANDOFF",
      verbatim: ["María Torres"],
    })
  })

  it("spends the turn only once the backend has answered", async () => {
    // Reading the transcript is not spending it. A backend that never answered has consumed
    // nothing, so the words stay available and a retry classifies what the person actually
    // said instead of asking them to repeat it.
    const commit = vi.fn()
    const processSpokenTurn = vi.fn().mockRejectedValue(new Error("sin red"))
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult: () => null,
        resolveSpokenText: async () => ({ text: "Me robaron la tarjeta.", commit }),
        processSpokenTurn,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "procesar_turno").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-6" } } as never,
    )

    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
    expect(commit).not.toHaveBeenCalled()
  })

  it("spends an answer it could not read, so it cannot bleed into the next one", async () => {
    // This was the answer to a question the kiosk did ask; it just was not a clear one.
    // Left unspent it would be glued onto whatever comes next, and "no sé" followed by "sí"
    // reads as a no.
    const commit = vi.fn()
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult: () => null,
        resolveSpokenText: async () => ({ text: "No sé", commit }),
        processSpokenTurn: vi.fn().mockResolvedValue({
          kind: "retry",
          guidance: "Pide una respuesta clara.",
        }),
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "procesar_turno").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-8" } } as never,
    )

    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
    expect(commit).toHaveBeenCalledTimes(1)
  })
})

describe("tool output", () => {
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

    const hoursOutput = flowToolOutput(automatic("hours", hours))
    const creditOutput = flowToolOutput(automatic("credit", credit))

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

  it("routes a COMPLETE analysis (GENERAL, no confirmation step) through the flow tool output", () => {
    const autoResolved: TurnAnalysis = {
      ...analysis,
      consultation_level: "GENERAL",
      next_action: "COMPLETE",
      speech_text: completed.speech_text,
      speech_plan: completed.speech_plan,
      result: completed,
    }
    expect(analysisToolOutput(autoResolved)).toEqual(flowToolOutput(completed))
  })

  it("carries the plan's own fields and never the written fallback", () => {
    const output = speechPlanToolOutput(completed.speech_plan, { next_action: "COMPLETE" })
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

describe("idle tool results", () => {
  // Three states in which the model calls `procesar_turno` and there is genuinely nothing
  // to do. Every one of them used to reach `/turns`, be refused by the backend guard, and
  // come back as "no pudiste consultar el sistema, discúlpate" -- which is what a customer
  // heard the moment the CI field appeared in front of them.
  it.each([
    ["awaiting_identification", "IDENTIFY"],
    ["settled", "SETTLED"],
    ["noop", "NOOP"],
  ] as const)("reports %s as a success the model must not apologise for", (kind, intent) => {
    const output = turnProcessingToolOutput({ kind })
    expect(output).toMatchObject({ ok: true, intent, next_action: "NONE" })
    expect(output.facts).toEqual({})
    expect(output.verbatim).toEqual([])
  })

  it("tells the model to wait in silence while the CI is typed", () => {
    const guidance = String(
      turnProcessingToolOutput({ kind: "awaiting_identification" }).guidance,
    )
    expect(guidance).toMatch(/campo protegido/i)
    expect(guidance).toMatch(/espera/i)
  })

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
  const transport = () => ({ sendMessage: vi.fn(), interrupt: vi.fn() })

  it("speaks immediately when nothing else is speaking", () => {
    const wire = transport()
    new SpeechFloor(wire).request("resume", () => "hola")
    expect(wire.sendMessage).toHaveBeenCalledWith("hola")
  })

  it("holds an injection until the current response is done", () => {
    // The SDK's sequencer queues a `response.create` that arrives mid-response rather than
    // dropping it, so an unarbitrated injection always came out eventually -- as a stray
    // sentence trailing the previous one.
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    floor.request("resume", () => "hola")
    expect(wire.sendMessage).not.toHaveBeenCalled()

    floor.noteResponseDone()
    expect(wire.sendMessage).toHaveBeenCalledWith("hola")
  })

  it("waits for a tool call as well as for speech", () => {
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteToolStarted()
    floor.request("resume", () => "hola")
    expect(wire.sendMessage).not.toHaveBeenCalled()
    floor.noteToolFinished()
    expect(wire.sendMessage).toHaveBeenCalledTimes(1)
  })

  it("drops a held injection whose state has moved on", () => {
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    let stillRelevant = true
    floor.request("resume", () => (stillRelevant ? "hola" : null))
    stillRelevant = false
    floor.noteResponseDone()
    expect(wire.sendMessage).not.toHaveBeenCalled()
  })

  it("coalesces repeated requests of the same kind, last one wins", () => {
    const wire = transport()
    const floor = new SpeechFloor(wire)
    floor.noteResponseStarted()
    floor.request("identification_close", () => "primero")
    floor.request("identification_close", () => "después")
    floor.noteResponseDone()
    expect(wire.sendMessage).toHaveBeenCalledTimes(1)
    expect(wire.sendMessage).toHaveBeenCalledWith("después")
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
    expect(wire.sendMessage).toHaveBeenCalledWith("ya quedó resuelto")
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

describe("tool choice release", () => {
  // `required` guarantees that every turn the person actually spoke is offered to the tool.
  // It must not also guarantee success: a backend outage leaves the words unconsumed on
  // purpose, so a retry classifies what was really said, and if that also kept the turn
  // "unspent" the model would be forced to call the tool again on every single response.
  it("stops forcing a tool call once the turn has been offered, even if it was not consumed", () => {
    const captions = [
      { id: "item-1", role: "user" as const, text: "Me robaron la tarjeta.", completed: true },
    ]
    const attempted = new Set<string>()
    const consumed = new Set<string>()
    const offered = () =>
      selectAuthoritativeTranscript(captions, {
        has: (id: string) => consumed.has(id) || attempted.has(id),
      }) !== null

    expect(offered()).toBe(true)
    attempted.add("item-1")
    expect(offered()).toBe(false)
    // The words themselves stay readable for the retry.
    expect(selectAuthoritativeTranscript(captions, consumed)).not.toBeNull()
  })
})

describe("results the model was never shown", () => {
  // Recorded 2026-09-01, session b7844a53. The customer asked for a consumer loan, confirmed
  // it, typed their CI, and was assigned ticket 1 at Ventanilla 4 with Roberto Torrez and an
  // 8-minute wait. What the kiosk actually said was: "el trámite quedó resuelto ... el
  // siguiente paso depende de la confirmación interna del proceso". Not one of those facts
  // was spoken, because the identity card is typed on a form: that outcome never passed
  // through speech, so no tool call ever carried its SpeechPlan to the model, and the
  // closing message told it to use "what the last tool returned" -- which was an idle
  // check-in with empty facts.
  const handoff: FlowResult = {
    ...completed,
    ticket: { id: "ticket-1", number: 1, status: "PENDIENTE", estimated_wait_minutes: 8 },
    speech_plan: {
      intent: "HANDOFF",
      facts: {
        ticket: "1",
        ventanilla: "Ventanilla 4",
        ejecutivo: "Roberto Torrez",
        espera_minutos: "8",
      },
      verbatim: ["Roberto Torrez"],
      guidance: "Dale el ticket, la ventanilla y el nombre exactamente como aparecen.",
      fallback_text: "Tu ticket es 1. Dirígete a Ventanilla 4 con Roberto Torrez.",
    },
  }

  it("hands a form-submitted outcome to the model ahead of anything that was said", async () => {
    const resolveSpokenText = vi.fn()
    const processSpokenTurn = vi.fn()
    const takePendingResult = vi
      .fn()
      .mockReturnValueOnce({ kind: "flow", response: handoff })
      .mockReturnValue(null)
    const agent = createKioskRealtimeAgent(
      { takePendingResult, resolveSpokenText, processSpokenTurn },
      agentOptions,
    )

    const output = await toolNamed(agent, "procesar_turno").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-identification" } } as never,
    )

    // The ticket, the window and the executive all reach the model as tool data.
    expect(output).toMatchObject({
      ok: true,
      intent: "HANDOFF",
      facts: handoff.speech_plan.facts,
      verbatim: ["Roberto Torrez"],
    })
    // There is no turn to transcribe: the card was typed, not spoken.
    expect(resolveSpokenText).not.toHaveBeenCalled()
    expect(processSpokenTurn).not.toHaveBeenCalled()
  })

  it("is spent once, so it cannot be announced twice", async () => {
    const takePendingResult = vi
      .fn()
      .mockReturnValueOnce({ kind: "flow", response: handoff })
      .mockReturnValue(null)
    const agent = createKioskRealtimeAgent(
      {
        takePendingResult,
        resolveSpokenText: async () => null,
        processSpokenTurn: vi.fn(),
      },
      agentOptions,
    )
    const tool = toolNamed(agent, "procesar_turno")

    const first = await tool.invoke({} as never, JSON.stringify({}), {
      toolCall: { callId: "call-1" },
    } as never)
    const second = await tool.invoke({} as never, JSON.stringify({}), {
      toolCall: { callId: "call-2" },
    } as never)

    expect(first).toMatchObject({ intent: "HANDOFF" })
    expect(second).toMatchObject({ intent: "NOOP" })
  })

  it("makes the delivering tool call mandatory", () => {
    // Nothing was said, so the transcript-based rule would leave tool choice on `auto` and
    // let the model narrate an outcome it had never been shown.
    expect(
      realtimeToolChoiceForTurn({
        greeted: true,
        hasUnspentTranscript: false,
        hasPendingResult: true,
      }),
    ).toBe("required")
  })
})
