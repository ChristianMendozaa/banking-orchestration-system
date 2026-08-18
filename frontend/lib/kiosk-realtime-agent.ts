import { RealtimeAgent, backgroundResult, tool } from "@openai/agents/realtime"
import { z } from "zod"

import {
  analysisToolOutput,
  errorToolOutput,
  explicitConfirmation,
  flowToolOutput,
  type KioskRealtimeCallbacks,
} from "@/lib/kiosk-realtime"

const AGENT_INSTRUCTIONS = `
Eres la asistente virtual femenina de un kiosco bancario en Bolivia.
Habla siempre en español boliviano claro, cordial, natural, breve y de tú. Conversa directamente
con la persona: nunca la llames "usuario", "cliente" ni "persona". Al comenzar, preséntate
explícitamente como asistente virtual y pregunta el motivo de atención.

REGLAS DE SEGURIDAD:
- Nunca solicites ni repitas PIN, CVV, contraseñas, códigos de verificación, credenciales,
  números completos de tarjeta, cuenta u otros datos financieros completos.
- El CI se escribe en un campo protegido. Nunca pidas que se dicte.
- No inventes información bancaria, categorías, prioridades, requisitos, respuestas documentales,
  tickets, ejecutivos ni ventanillas.
- No describas herramientas, JSON, estados internos ni detalles técnicos.

FLUJO OBLIGATORIO:
1. Escucha el motivo. Cuando haya una petición comprensible, llama a analizar_requerimiento con
   una transcripción fiel de ese último turno; no clasifiques ni respondas por tu cuenta.
2. Si la tool devuelve CLARIFY, la aplicación pronunciará speech_text. Tras la respuesta,
   vuelve a llamar analizar_requerimiento solo con esa aclaración; el backend conserva el contexto.
3. Si devuelve CONFIRM, la aplicación pronunciará speech_text; espera un sí o no inequívoco.
3b. Si analizar_requerimiento devuelve COMPLETE con resolution_type AUTOMATIC, la petición
    era información pública y ya quedó resuelta sin necesitar confirmación. La aplicación
    pronunciará la respuesta. No pidas confirmación ni repitas la respuesta, pero sigue
    escuchando: si la persona hace otra consulta distinta, vuelve a llamar
    analizar_requerimiento con ese nuevo turno. Si en cambio devuelve COMPLETE con un
    número de ticket, la atención pasó a un ejecutivo: no continúes la conversación.
4. Solo llama confirmar_requerimiento cuando recibas una confirmación o rechazo
   explícita. Copia sus palabras en user_response y no infieras una confirmación.
5. La aplicación pronunciará el resultado de cada herramienta. Llama la herramienta directamente:
   no digas frases de espera, no hables después de llamarla y no repitas su resultado.
6. Si la confirmación devuelve CAPTURE, espera que vuelva a describir el caso.
7. Si devuelve IDENTIFY, deja de hacer preguntas mientras escribe el CI en pantalla.
8. Si devuelve COMPLETE con un número de ticket, la atención pasó a un ejecutivo: no
   continúes la conversación.
9. Si analizar_requerimiento devuelve DECLINE, la aplicación pronunciará speech_text
   explicando qué sí puede resolver el kiosco. No insistas, no pidas confirmación y no
   continúes la conversación.
`.trim()

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim()
}

export function createKioskRealtimeAgent(
  callbacks: KioskRealtimeCallbacks,
): RealtimeAgent {
  const analyzeRequirement = tool({
    name: "analizar_requerimiento",
    description:
      "Envía el último turno hablado al backend seguro para enmascarar PII, clasificar, priorizar y decidir el siguiente paso.",
    parameters: z.object({ transcript: z.string().min(2).max(4000) }),
    timeoutMs: 25_000,
    async execute({ transcript }, _context, details) {
      try {
        return backgroundResult(
          analysisToolOutput(
            await callbacks.analyzeRequirement(
              compactText(transcript),
              details?.toolCall?.callId,
            ),
          ),
        )
      } catch {
        return backgroundResult(
          errorToolOutput(
            "analizar_requerimiento",
            details?.toolCall?.callId,
            "No pude analizar tu solicitud en este momento. Pide ayuda o intenta nuevamente.",
          ),
        )
      }
    },
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
    async execute({ confirmed, user_response }, _context, details) {
      const detected = explicitConfirmation(user_response)
      if (detected === null || detected !== confirmed) {
        return backgroundResult({
          ok: false,
          next_action: "ASK_EXPLICIT_CONFIRMATION",
          speech_text: "Por favor, respóndeme claramente sí para confirmar o no para corregir.",
          transition_key: `confirmar_requerimiento:${details?.toolCall?.callId ?? crypto.randomUUID()}:ASK_EXPLICIT_CONFIRMATION`,
        })
      }
      try {
        return backgroundResult(
          flowToolOutput(
            await callbacks.confirmRequirement(detected, details?.toolCall?.callId),
          ),
        )
      } catch {
        return backgroundResult(
          errorToolOutput(
            "confirmar_requerimiento",
            details?.toolCall?.callId,
            "No pude registrar tu confirmación en este momento. Pide ayuda o intenta nuevamente.",
          ),
        )
      }
    },
  })

  return new RealtimeAgent({
    name: "Asistente virtual del kiosco",
    voice: "marin",
    instructions: AGENT_INSTRUCTIONS,
    tools: [analyzeRequirement, confirmRequirement],
  })
}
