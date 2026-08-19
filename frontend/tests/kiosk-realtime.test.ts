import { isBackgroundResult } from "@openai/agents/realtime"
import { describe, expect, it, vi } from "vitest"

import {
  analysisToolOutput,
  APPLICATION_EVENT_PREFIX,
  analysisTransitionKey,
  businessTransitionKey,
  canReplayControlledSpeech,
  captionsFromHistory,
  controlledTransitionFromToolResult,
  isTerminalFlowResult,
  explicitConfirmation,
  flowToolOutput,
  flowTransitionKey,
  requestControlledResponse,
  selectAuthoritativeTranscript,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  shouldReplayControlledTransition,
  transcriptsDiverge,
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
  speech_text: "Me confirmas si necesitas reportar un fraude en tu tarjeta.",
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
  speech_text: "Tu ticket es el número 4.",
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

describe("transcriptsDiverge", () => {
  it("flags the corruption seen in production", () => {
    // The kiosk transcribed this correctly and the model typed the second version into the
    // tool call; the backend classified the second one and asked the customer whether they
    // meant "portar el juego de tu tarjeta".
    expect(
      transcriptsDiverge(
        "Quiero reportar el robo de mi tarjeta de débito.",
        "Quiero portar el juego de mi tarjeta de débito.",
      ),
    ).toBe(true)
  })

  it("tolerates ordinary punctuation and accent differences", () => {
    expect(
      transcriptsDiverge(
        "Quiero reportar el robo de mi tarjeta de débito.",
        "quiero reportar el robo de mi tarjeta de debito",
      ),
    ).toBe(false)
  })

  it("says nothing when there is no model text to compare against", () => {
    expect(transcriptsDiverge("Quiero bloquear mi tarjeta.", "")).toBe(false)
  })
})

describe("createKioskRealtimeAgent", () => {
  it("exposes only the tools that delegate to the backend", () => {
    const agent = createKioskRealtimeAgent({
      resolveSpokenText: async (fallback: string) => fallback,
      analyzeRequirement: vi.fn(),
      confirmRequirement: vi.fn(),
    })

    expect(agent.voice).toBe("marin")
    expect(agent.tools.map((item) => item.name)).toEqual([
      "analizar_requerimiento",
      "confirmar_requerimiento",
    ])
  })

  it("returns results in the background to prevent the SDK from auto-responding", async () => {
    const analyzeRequirement = vi.fn().mockResolvedValue(analysis)
    const agent = createKioskRealtimeAgent({
      resolveSpokenText: async (fallback: string) => fallback,
      analyzeRequirement,
      confirmRequirement: vi.fn(),
    })
    const analyzeTool = agent.tools.find(
      (candidate) => candidate.type === "function" && candidate.name === "analizar_requerimiento",
    )
    if (!analyzeTool || analyzeTool.type !== "function") {
      throw new Error("No se encontró la herramienta de análisis")
    }

    const output = await analyzeTool.invoke(
      {} as never,
      JSON.stringify({ fallback_transcript: "  Fraude   en mi tarjeta " }),
      { toolCall: { callId: "call-1" } } as never,
    )

    expect(analyzeRequirement).toHaveBeenCalledWith("Fraude en mi tarjeta", "call-1")
    expect(isBackgroundResult(output)).toBe(true)
    if (!isBackgroundResult<Record<string, unknown>>(output)) return
    expect(output.content).toMatchObject({
      customer_summary: analysis.customer_summary,
      next_action: "CONFIRM",
      speech_text: analysis.speech_text,
      transition_key: "requirement-1:CONFIRM",
    })
  })

  it("also keeps confirmation out of the automatic continuation", async () => {
    const confirmRequirement = vi.fn().mockResolvedValue(completed)
    const agent = createKioskRealtimeAgent({
      resolveSpokenText: async (fallback: string) => fallback,
      analyzeRequirement: vi.fn(),
      confirmRequirement,
    })
    const confirmTool = agent.tools.find(
      (candidate) =>
        candidate.type === "function" && candidate.name === "confirmar_requerimiento",
    )
    if (!confirmTool || confirmTool.type !== "function") {
      throw new Error("No se encontró la herramienta de confirmación")
    }

    const output = await confirmTool.invoke(
      {} as never,
      JSON.stringify({ confirmed: true, user_response: "Sí, es correcto" }),
      { toolCall: { callId: "call-2" } } as never,
    )

    expect(confirmRequirement).toHaveBeenCalledWith(true, "call-2")
    expect(isBackgroundResult(output)).toBe(true)
    if (!isBackgroundResult<Record<string, unknown>>(output)) return
    expect(output.content).toMatchObject({
      next_action: "COMPLETE",
      transition_key: "ticket:ticket-1",
    })
  })

  it("classifies the transcription, not the model's retelling of it", async () => {
    // The production failure this exists to prevent: the customer said "reportar el robo" and
    // the model typed "portar el juego" into the tool call.
    const analyzeRequirement = vi.fn().mockResolvedValue(analysis)
    const agent = createKioskRealtimeAgent({
      resolveSpokenText: async () => "Quiero reportar el robo de mi tarjeta de débito.",
      analyzeRequirement,
      confirmRequirement: vi.fn(),
    })
    const analyzeTool = agent.tools.find(
      (candidate) => candidate.type === "function" && candidate.name === "analizar_requerimiento",
    )
    if (!analyzeTool || analyzeTool.type !== "function") {
      throw new Error("No se encontró la herramienta de análisis")
    }

    await analyzeTool.invoke(
      {} as never,
      JSON.stringify({ fallback_transcript: "Quiero portar el juego de mi tarjeta de débito." }),
      { toolCall: { callId: "call-9" } } as never,
    )

    expect(analyzeRequirement).toHaveBeenCalledWith(
      "Quiero reportar el robo de mi tarjeta de débito.",
      "call-9",
    )
  })

  it("refuses a confirmation the transcription does not support", async () => {
    // A mis-heard "no" would otherwise open a case the customer just declined: `confirmed`
    // is the model's own reading, and it has to agree with what was actually transcribed.
    const confirmRequirement = vi.fn()
    const agent = createKioskRealtimeAgent({
      resolveSpokenText: async () => "No, eso no es lo que necesito",
      analyzeRequirement: vi.fn(),
      confirmRequirement,
    })
    const confirmTool = agent.tools.find(
      (candidate) =>
        candidate.type === "function" && candidate.name === "confirmar_requerimiento",
    )
    if (!confirmTool || confirmTool.type !== "function") {
      throw new Error("No se encontró la herramienta de confirmación")
    }

    const output = await confirmTool.invoke(
      {} as never,
      JSON.stringify({ confirmed: true, user_response: "Sí, correcto" }),
      { toolCall: { callId: "call-10" } } as never,
    )

    expect(confirmRequirement).not.toHaveBeenCalled()
    if (!isBackgroundResult<Record<string, unknown>>(output)) return
    expect(output.content).toMatchObject({ next_action: "ASK_EXPLICIT_CONFIRMATION" })
  })

  it("asks for an unambiguous confirmation without calling the backend or auto-responding", async () => {
    const confirmRequirement = vi.fn()
    const agent = createKioskRealtimeAgent({
      resolveSpokenText: async (fallback: string) => fallback,
      analyzeRequirement: vi.fn(),
      confirmRequirement,
    })
    const confirmTool = agent.tools.find(
      (candidate) =>
        candidate.type === "function" && candidate.name === "confirmar_requerimiento",
    )
    if (!confirmTool || confirmTool.type !== "function") {
      throw new Error("No se encontró la herramienta de confirmación")
    }

    const output = await confirmTool.invoke(
      {} as never,
      JSON.stringify({ confirmed: true, user_response: "Puede ser" }),
      { toolCall: { callId: "call-ambiguous" } } as never,
    )

    expect(confirmRequirement).not.toHaveBeenCalled()
    expect(isBackgroundResult(output)).toBe(true)
    if (!isBackgroundResult<Record<string, unknown>>(output)) return
    expect(output.content).toMatchObject({
      next_action: "ASK_EXPLICIT_CONFIRMATION",
      transition_key:
        "confirmar_requerimiento:call-ambiguous:ASK_EXPLICIT_CONFIRMATION",
    })
  })
})

describe("transition keys", () => {
  it("correlates analysis and tickets with stable keys", () => {
    expect(analysisTransitionKey(analysis)).toBe("requirement-1:CONFIRM")
    expect(flowTransitionKey(completed)).toBe("ticket:ticket-1")
  })

  it("routes a COMPLETE analysis (GENERAL, no confirmation step) through the flow tool output", () => {
    const autoResolved: TurnAnalysis = {
      ...analysis,
      consultation_level: "GENERAL",
      next_action: "COMPLETE",
      speech_text: completed.speech_text,
      result: completed,
    }
    expect(analysisToolOutput(autoResolved)).toEqual(flowToolOutput(completed))
  })

  it("extracts only controllable results and detects closure", () => {
    expect(
      controlledTransitionFromToolResult(
        JSON.stringify({
          transition_key: "ticket:ticket-1",
          speech_text: "  Tu ticket es el número 4.  ",
          next_action: "COMPLETE",
        }),
      ),
    ).toEqual({
      transitionKey: "ticket:ticket-1",
      speechText: "Tu ticket es el número 4.",
      nextAction: "COMPLETE",
      terminal: true,
    })
    expect(controlledTransitionFromToolResult("sin json")).toBeNull()
  })

  it("does not treat an automatic answer as the end of the session", () => {
    // An answer the kiosk produced by itself leaves the customer standing there, and the
    // backend now opens a second case for a follow-up question, so closing the session on
    // COMPLETE would hang up on someone mid-conversation.
    expect(
      controlledTransitionFromToolResult(
        JSON.stringify({
          transition_key: "answer:requirement-9",
          speech_text: "Las agencias atienden de 08:30 a 19:00.",
          next_action: "COMPLETE",
          resolution_type: "AUTOMATIC",
        }),
      ),
    ).toMatchObject({ nextAction: "COMPLETE", terminal: false })
  })

  it("still closes the session on a human handoff", () => {
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
    expect(businessTransitionKey({ analysis, result: completed })).toBe(
      "ticket:ticket-1",
    )
  })

  it("only retries interrupted audio while the transition is still valid", () => {
    const transition = {
      transitionKey: analysisTransitionKey(analysis),
      speechText: analysis.speech_text,
      nextAction: analysis.next_action,
      terminal: false,
    }
    expect(
      shouldReplayControlledTransition(
        { analysis, result: null },
        transition,
        3,
        4,
      ),
    ).toBe(true)
    expect(
      shouldReplayControlledTransition(
        { analysis, result: completed },
        transition,
        3,
        4,
      ),
    ).toBe(false)
    expect(
      shouldReplayControlledTransition(
        { analysis: null, result: null },
        { ...transition, transitionKey: "session-1:WELCOME", nextAction: "WELCOME" },
        3,
        4,
      ),
    ).toBe(false)
  })

  it("limits an utterance's automatic retry to one", () => {
    expect(canReplayControlledSpeech(0)).toBe(true)
    expect(canReplayControlledSpeech(1)).toBe(false)
  })
})

describe("requestControlledResponse", () => {
  it("generates a response without creating a user message and without tools", () => {
    const requestResponse = vi.fn()
    const sendEvent = vi.fn()

    requestControlledResponse(
      { transport: { requestResponse, sendEvent } } as never,
      "Saluda y pregunta el motivo de atención.",
      "session-1:WELCOME",
    )

    expect(requestResponse).toHaveBeenCalledWith({
      instructions: "Saluda y pregunta el motivo de atención.",
      tools: [],
      tool_choice: "none",
      metadata: { transition_key: "session-1:WELCOME" },
    })
    expect(sendEvent).not.toHaveBeenCalled()
  })
})
