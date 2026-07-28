import { isBackgroundResult } from "@openai/agents/realtime"
import { describe, expect, it, vi } from "vitest"

import {
  APPLICATION_EVENT_PREFIX,
  analysisTransitionKey,
  businessTransitionKey,
  canReplayControlledSpeech,
  captionsFromHistory,
  controlledTransitionFromToolResult,
  explicitConfirmation,
  flowTransitionKey,
  requestControlledResponse,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  shouldReplayControlledTransition,
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
  it("muestra solo mensajes del usuario y la asistente, sin eventos internos", () => {
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

describe("createKioskRealtimeAgent", () => {
  it("expone únicamente las tools que delegan al backend", () => {
    const agent = createKioskRealtimeAgent({
      analyzeRequirement: vi.fn(),
      confirmRequirement: vi.fn(),
    })

    expect(agent.voice).toBe("marin")
    expect(agent.tools.map((item) => item.name)).toEqual([
      "analizar_requerimiento",
      "confirmar_requerimiento",
    ])
  })

  it("devuelve resultados en segundo plano para impedir la respuesta automática del SDK", async () => {
    const analyzeRequirement = vi.fn().mockResolvedValue(analysis)
    const agent = createKioskRealtimeAgent({
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
      JSON.stringify({ transcript: "  Fraude   en mi tarjeta " }),
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

  it("mantiene también la confirmación fuera de la continuación automática", async () => {
    const confirmRequirement = vi.fn().mockResolvedValue(completed)
    const agent = createKioskRealtimeAgent({
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

  it("pide una confirmación inequívoca sin invocar el backend ni auto-responder", async () => {
    const confirmRequirement = vi.fn()
    const agent = createKioskRealtimeAgent({
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

describe("claves de transición", () => {
  it("correlaciona análisis y tickets con claves estables", () => {
    expect(analysisTransitionKey(analysis)).toBe("requirement-1:CONFIRM")
    expect(flowTransitionKey(completed)).toBe("ticket:ticket-1")
  })

  it("extrae únicamente resultados controlables y detecta el cierre", () => {
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
})

describe("orden de respuestas de negocio", () => {
  it("no deja que un análisis retrasado borre identificación o cierre", () => {
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

  it("acepta el avance de una aclaración si solo se reconcilió su fase inicial", () => {
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

  it("no revive un requerimiento que ya fue rechazado", () => {
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

  it("no deja que IDENTIFY retrasado reemplace un ticket COMPLETE", () => {
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

  it("solo reintenta audio interrumpido mientras la transición siga vigente", () => {
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

  it("limita a uno el reintento automático de una locución", () => {
    expect(canReplayControlledSpeech(0)).toBe(true)
    expect(canReplayControlledSpeech(1)).toBe(false)
  })
})

describe("requestControlledResponse", () => {
  it("genera una respuesta sin crear un mensaje de usuario y sin herramientas", () => {
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
