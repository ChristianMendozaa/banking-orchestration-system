import {
  RealtimeAgent,
  type RealtimeItem,
  type RealtimeSession,
  tool,
} from "@openai/agents/realtime"
import { z } from "zod"

import type { FlowResult, TurnAnalysis } from "@/lib/types"

export const APPLICATION_EVENT_PREFIX = "[EVENTO_APLICACION]"

export interface ConversationCaption {
  id: string
  role: "user" | "assistant"
  text: string
  completed: boolean
}

export interface KioskRealtimeCallbacks {
  analyzeRequirement: (transcript: string, callId?: string) => Promise<TurnAnalysis>
  confirmRequirement: (confirmed: boolean) => Promise<FlowResult>
}

export function requestControlledResponse(
  realtime: Pick<RealtimeSession, "transport">,
  instructions: string,
): void {
  const response = {
    instructions,
    tools: [],
  }
  if (realtime.transport.requestResponse) {
    realtime.transport.requestResponse(response)
    return
  }
  realtime.transport.sendEvent({ type: "response.create", response })
}

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim()
}

function normalizeConfirmation(value: string): string {
  return compactText(value)
    .toLocaleLowerCase("es")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
}

export function explicitConfirmation(value: string): boolean | null {
  const normalized = normalizeConfirmation(value)
  const negative =
    /\b(no|incorrecto|incorrecta|corregir|correccion|cambiar|equivocado|equivocada)\b/.test(
      normalized,
    )
  const positive =
    /\b(si|correcto|correcta|confirmo|confirmar|de acuerdo|esta bien|es correcto|es correcta)\b/.test(
      normalized,
    )

  if (positive === negative) return null
  return positive
}

export function captionsFromHistory(history: RealtimeItem[]): ConversationCaption[] {
  return history.flatMap((item): ConversationCaption[] => {
    if (item.type !== "message" || item.role === "system") return []

    const text = compactText(
      item.content
        .map((part) => {
          if (part.type === "input_text") return part.text
          if (part.type === "input_audio") return part.transcript ?? ""
          if (part.type === "output_text") return part.text
          if (part.type === "output_audio") return part.transcript ?? ""
          return ""
        })
        .filter(Boolean)
        .join(" "),
    )
    if (!text || text.startsWith(APPLICATION_EVENT_PREFIX)) return []

    return [
      {
        id: item.itemId,
        role: item.role,
        text,
        completed: item.status === "completed",
      },
    ]
  })
}

function analysisToolOutput(response: TurnAnalysis): string {
  return JSON.stringify({
    ok: true,
    next_action: response.next_action,
    speech_text: response.speech_text,
    protected_summary: response.summary,
    category: response.category,
    priority: response.priority,
    consultation_level: response.consultation_level,
    clarification_question: response.clarification_question,
  })
}

function flowToolOutput(response: FlowResult): string {
  return JSON.stringify({
    ok: true,
    next_action: response.next_action,
    speech_text: response.speech_text,
    resolution_type: response.resolution_type,
    identification_status: response.identification_status,
    response: response.response,
    ticket: response.ticket,
    executive: response.executive,
  })
}

const AGENT_INSTRUCTIONS = `
Eres la asistente virtual femenina de un kiosco bancario en Bolivia.
Habla siempre en español boliviano claro, cordial, natural y breve. Al comenzar, preséntate
explícitamente como asistente virtual y pregunta el motivo de atención.

REGLAS DE SEGURIDAD:
- Nunca solicites ni repitas PIN, CVV, contraseñas, códigos de verificación, credenciales,
  números completos de tarjeta, cuenta u otros datos financieros completos.
- El código de cliente se escribe en un campo protegido. Nunca pidas que se dicte.
- No inventes información bancaria, categorías, prioridades, requisitos, respuestas documentales,
  tickets, ejecutivos ni ventanillas.
- No describas herramientas, JSON, estados internos ni detalles técnicos.

FLUJO OBLIGATORIO:
1. Escucha el motivo. Cuando haya una petición comprensible, llama a analizar_requerimiento con
   una transcripción fiel de ese último turno; no clasifiques ni respondas por tu cuenta.
2. Si la tool devuelve CLARIFY, pronuncia exactamente speech_text. Tras la respuesta del cliente,
   vuelve a llamar analizar_requerimiento solo con esa aclaración; el backend conserva el contexto.
3. Si devuelve CONFIRM, pronuncia fielmente speech_text y espera un sí o no inequívoco.
4. Solo llama confirmar_requerimiento cuando la persona haya confirmado o rechazado de forma
   explícita. Copia sus palabras en user_response y no infieras una confirmación.
5. Si la confirmación devuelve CAPTURE, pronuncia speech_text y pide describir nuevamente el caso.
6. Si devuelve IDENTIFY, pronuncia speech_text, explica que debe escribir el código de cliente
   en pantalla y deja de hacer preguntas.
7. Si devuelve COMPLETE, pronuncia fielmente speech_text. Conserva exactamente los números de
   ticket y ventanilla y termina con una despedida breve.
Mientras una tool trabaja puedes decir una sola frase corta como "Un momento, por favor".
`.trim()

export function createKioskRealtimeAgent(callbacks: KioskRealtimeCallbacks): RealtimeAgent {
  const analyzeRequirement = tool({
    name: "analizar_requerimiento",
    description:
      "Envía el último turno hablado al backend seguro para enmascarar PII, clasificar, priorizar y decidir el siguiente paso.",
    parameters: z.object({
      transcript: z.string().min(2).max(4000),
    }),
    timeoutMs: 25_000,
    async execute({ transcript }, _context, details) {
      const response = await callbacks.analyzeRequirement(
        compactText(transcript),
        details?.toolCall?.callId,
      )
      return analysisToolOutput(response)
    },
    errorFunction: () =>
      JSON.stringify({
        ok: false,
        speech_text:
          "No pude analizar el requerimiento en este momento. Pida ayuda o intente nuevamente.",
      }),
  })

  const confirmRequirement = tool({
    name: "confirmar_requerimiento",
    description:
      "Confirma o rechaza el resumen protegido únicamente después de escuchar una respuesta explícita de la persona.",
    parameters: z.object({
      confirmed: z.boolean(),
      user_response: z.string().min(1).max(200),
    }),
    timeoutMs: 25_000,
    async execute({ confirmed, user_response }) {
      const detected = explicitConfirmation(user_response)
      if (detected === null || detected !== confirmed) {
        return JSON.stringify({
          ok: false,
          next_action: "ASK_EXPLICIT_CONFIRMATION",
          speech_text: "Por favor responda claramente sí para confirmar o no para corregir.",
        })
      }
      return flowToolOutput(await callbacks.confirmRequirement(detected))
    },
    errorFunction: () =>
      JSON.stringify({
        ok: false,
        speech_text:
          "No pude registrar la confirmación en este momento. Pida ayuda o intente nuevamente.",
      }),
  })

  return new RealtimeAgent({
    name: "Asistente virtual del kiosko",
    voice: "marin",
    instructions: AGENT_INSTRUCTIONS,
    tools: [analyzeRequirement, confirmRequirement],
  })
}
