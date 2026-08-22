import { describe, expect, it, vi } from "vitest"

import {
  analysisToolOutput,
  APPLICATION_EVENT_PREFIX,
  captionsFromHistory,
  isTerminalFlowResult,
  explicitConfirmation,
  flowToolOutput,
  missingVerbatim,
  selectAuthoritativeTranscript,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  speechPlanToolOutput,
} from "../lib/kiosk-realtime"
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
    verbatim: ["Ventanilla 3", "María Torres"],
    guidance: "Dale el ticket, la ventanilla y el nombre exactamente como aparecen.",
    fallback_text: "Tu ticket es 4. Dirígete a Ventanilla 3 con María Torres.",
  },
  tracking_information: null,
  grounding_status: "NOT_APPLICABLE",
  citations: [],
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
        "Ventanilla 3",
        "María Torres",
      ]),
    ).toEqual(["Ventanilla 3", "María Torres"])
  })

  it("reports everything when nothing was said at all", () => {
    expect(missingVerbatim("", ["Ventanilla 3"])).toEqual(["Ventanilla 3"])
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
        resolveSpokenText: async () => null,
        hasPendingRequirement: () => true,
        analyzeRequirement: vi.fn(),
        confirmRequirement: vi.fn(),
      },
      agentOptions,
    )

    expect(agent.voice).toBe("marin")
    expect(agent.instructions).toBe(agentOptions.instructions)
    expect(agent.tools.map((item) => item.name)).toEqual([
      "analizar_requerimiento",
      "confirmar_requerimiento",
    ])
  })

  it("hands the model facts and guidance, never a sentence to read out", async () => {
    // The whole point of the change: a tool result is raw material for the model's own
    // wording. `speech_text` deliberately does not reach it.
    const analyzeRequirement = vi.fn().mockResolvedValue(analysis)
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: async () => ({ text: "Me robaron la tarjeta.", commit: vi.fn() }),
        hasPendingRequirement: () => true,
        analyzeRequirement,
        confirmRequirement: vi.fn(),
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "analizar_requerimiento").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-1" } } as never,
    )

    expect(analyzeRequirement).toHaveBeenCalledWith("Me robaron la tarjeta.", "call-1")
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
        resolveSpokenText: async () => ({ text: "Quiero reportar el robo de mi tarjeta de débito.", commit: vi.fn() }),
        hasPendingRequirement: () => true,
        analyzeRequirement: vi.fn().mockResolvedValue(analysis),
        confirmRequirement: vi.fn(),
      },
      agentOptions,
    )
    const analyzeTool = toolNamed(agent, "analizar_requerimiento")

    expect(
      Object.keys(
        (analyzeTool.parameters as { properties?: Record<string, unknown> }).properties ?? {},
      ),
    ).toEqual([])
  })

  it("asks the person to repeat when the transcription never landed", async () => {
    // There is no second-best transcript. Inventing one is the bug this replaced.
    const analyzeRequirement = vi.fn()
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: async () => null,
        hasPendingRequirement: () => true,
        analyzeRequirement,
        confirmRequirement: vi.fn(),
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "analizar_requerimiento").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-2" } } as never,
    )

    expect(analyzeRequirement).not.toHaveBeenCalled()
    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
  })

  it("passes the terminal facts through as strings the model must keep intact", async () => {
    const confirmRequirement = vi.fn().mockResolvedValue(completed)
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: async () => ({ text: "Sí, es correcto", commit: vi.fn() }),
        hasPendingRequirement: () => true,
        analyzeRequirement: vi.fn(),
        confirmRequirement,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "confirmar_requerimiento").invoke(
      {} as never,
      JSON.stringify({ confirmed: true }),
      { toolCall: { callId: "call-3" } } as never,
    )

    expect(confirmRequirement).toHaveBeenCalledWith(true, "call-3")
    expect(output).toMatchObject({
      next_action: "COMPLETE",
      intent: "HANDOFF",
      verbatim: ["Ventanilla 3", "María Torres"],
    })
  })

  it("refuses a confirmation the transcription does not support", async () => {
    // A mis-heard "no" would otherwise open a case the customer just declined: `confirmed`
    // is the model's own reading, and it has to agree with what was actually transcribed.
    const confirmRequirement = vi.fn()
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: async () => ({ text: "No, eso no es lo que necesito", commit: vi.fn() }),
        hasPendingRequirement: () => true,
        analyzeRequirement: vi.fn(),
        confirmRequirement,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "confirmar_requerimiento").invoke(
      {} as never,
      JSON.stringify({ confirmed: true }),
      { toolCall: { callId: "call-4" } } as never,
    )

    expect(confirmRequirement).not.toHaveBeenCalled()
    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
  })

  it("re-asks an ambiguous answer without calling the backend", async () => {
    const confirmRequirement = vi.fn()
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: async () => ({ text: "Puede ser", commit: vi.fn() }),
        hasPendingRequirement: () => true,
        analyzeRequirement: vi.fn(),
        confirmRequirement,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "confirmar_requerimiento").invoke(
      {} as never,
      JSON.stringify({ confirmed: true }),
      { toolCall: { callId: "call-5" } } as never,
    )

    expect(confirmRequirement).not.toHaveBeenCalled()
    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
  })

  it("spends the turn only once the backend has answered", async () => {
    // Reading the transcript is not spending it. A backend that never answered has consumed
    // nothing, so the words stay available and a retry classifies what the person actually
    // said instead of asking them to repeat it.
    const commit = vi.fn()
    const analyzeRequirement = vi.fn().mockRejectedValue(new Error("sin red"))
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: async () => ({ text: "Me robaron la tarjeta.", commit }),
        hasPendingRequirement: () => true,
        analyzeRequirement,
        confirmRequirement: vi.fn(),
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "analizar_requerimiento").invoke(
      {} as never,
      JSON.stringify({}),
      { toolCall: { callId: "call-6" } } as never,
    )

    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
    expect(commit).not.toHaveBeenCalled()
  })

  it("does not read the turn at all when there is nothing to confirm", async () => {
    // Called out of order, this tool would otherwise spend the person's opening request as
    // if it were a yes or a no, and `analizar_requerimiento` would find nothing left to
    // classify -- the theft report would be gone.
    const commit = vi.fn()
    const resolveSpokenText = vi.fn()
    const confirmRequirement = vi.fn()
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: resolveSpokenText.mockResolvedValue({
          text: "Quiero reportar el robo de mi tarjeta de débito.",
          commit,
        }),
        hasPendingRequirement: () => false,
        analyzeRequirement: vi.fn(),
        confirmRequirement,
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "confirmar_requerimiento").invoke(
      {} as never,
      JSON.stringify({ confirmed: true }),
      { toolCall: { callId: "call-7" } } as never,
    )

    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
    expect(resolveSpokenText).not.toHaveBeenCalled()
    expect(commit).not.toHaveBeenCalled()
    expect(confirmRequirement).not.toHaveBeenCalled()
  })

  it("spends an answer it could not read, so it cannot bleed into the next one", async () => {
    // This was the answer to a question the kiosk did ask; it just was not a clear one.
    // Left unspent it would be glued onto whatever comes next, and "no sé" followed by "sí"
    // reads as a no.
    const commit = vi.fn()
    const agent = createKioskRealtimeAgent(
      {
        resolveSpokenText: async () => ({ text: "No sé", commit }),
        hasPendingRequirement: () => true,
        analyzeRequirement: vi.fn(),
        confirmRequirement: vi.fn(),
      },
      agentOptions,
    )

    const output = await toolNamed(agent, "confirmar_requerimiento").invoke(
      {} as never,
      JSON.stringify({ confirmed: true }),
      { toolCall: { callId: "call-8" } } as never,
    )

    expect(output).toMatchObject({ ok: false, intent: "RETRY" })
    expect(commit).toHaveBeenCalledTimes(1)
  })
})

describe("tool output", () => {
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
    expect(isTerminalFlowResult({ ...completed, resolution_type: "AUTOMATIC" })).toBe(
      false,
    )
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
    const answered = { ...completed, resolution_type: "AUTOMATIC" as const }
    const followUp = {
      ...answered,
      requirement_id: "requirement-2",
      ticket: { ...completed.ticket!, id: "ticket-2", number: 5 },
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
