import { describe, expect, it, vi } from "vitest"

import {
  APPLICATION_EVENT_PREFIX,
  captionsFromHistory,
  createKioskRealtimeAgent,
  explicitConfirmation,
  requestControlledResponse,
} from "../lib/kiosk-realtime"

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
})

describe("requestControlledResponse", () => {
  it("genera una respuesta sin crear un mensaje de usuario y sin herramientas", () => {
    const requestResponse = vi.fn()
    const sendEvent = vi.fn()

    requestControlledResponse(
      { transport: { requestResponse, sendEvent } } as never,
      "Saluda y pregunta el motivo de atención.",
    )

    expect(requestResponse).toHaveBeenCalledWith({
      instructions: "Saluda y pregunta el motivo de atención.",
      tools: [],
    })
    expect(sendEvent).not.toHaveBeenCalled()
  })
})
