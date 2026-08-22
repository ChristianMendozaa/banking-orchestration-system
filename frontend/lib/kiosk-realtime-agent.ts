import { RealtimeAgent, tool } from "@openai/agents/realtime"
import { z } from "zod"

import {
  analysisToolOutput,
  errorToolOutput,
  explicitConfirmation,
  flowToolOutput,
  type KioskRealtimeCallbacks,
} from "@/lib/kiosk-realtime"

export function createKioskRealtimeAgent(
  callbacks: KioskRealtimeCallbacks,
  options: { instructions: string; voice: string },
): RealtimeAgent {
  const analyzeRequirement = tool({
    name: "analizar_requerimiento",
    description:
      "Envía al backend seguro lo que la persona acaba de decir, para enmascarar datos " +
      "personales, clasificar el requerimiento, priorizarlo y decidir el siguiente paso. " +
      "Llámala cuando ya entendiste qué necesita. No recibe parámetros: la aplicación " +
      "adjunta por sí misma la transcripción oficial de ese turno.",
    // Deliberately empty. The model used to type what it thought it heard into a
    // `fallback_transcript` argument, and the backend classified that -- on 2026-08-19
    // "reportar el robo de mi tarjeta" reached the classifier as "portar el juego de mi
    // tarjeta". With no argument to type into, that class of corruption cannot happen: the
    // only transcript that exists is the session's own transcription.
    parameters: z.object({}),
    timeoutMs: 25_000,
    async execute(_args, _context, details) {
      const turn = await callbacks.resolveSpokenText()
      if (!turn) {
        return errorToolOutput(
          "Todavía no tienes lo que dijo. Pídele que te lo repita, con tus palabras.",
        )
      }
      try {
        const response = await callbacks.analyzeRequirement(
          turn.text,
          details?.toolCall?.callId,
        )
        // Only now are those words spent. A backend that never answered has not consumed
        // anything, and leaving the turn unspent means a retry classifies what the person
        // actually said instead of asking them to say it again.
        turn.commit()
        return analysisToolOutput(response)
      } catch {
        return errorToolOutput(
          "No pudiste consultar el sistema. Discúlpate brevemente y dile que lo intente " +
            "otra vez o que pida ayuda a un ejecutivo.",
        )
      }
    },
  })

  const confirmRequirement = tool({
    name: "confirmar_requerimiento",
    description:
      "Registra la confirmación o el rechazo del resumen. Llámala solo después de escuchar " +
      "un sí o un no claro.",
    parameters: z.object({
      confirmed: z.boolean(),
    }),
    timeoutMs: 25_000,
    async execute({ confirmed }, _context, details) {
      // Checked before the turn is even read. Called out of order -- before there is
      // anything to confirm -- this tool would otherwise read and spend the person's opening
      // request as if it were a yes or a no, and `analizar_requerimiento` would find nothing
      // left to classify.
      if (!callbacks.hasPendingRequirement()) {
        return errorToolOutput(
          "Todavía no hay nada que confirmar. Primero entiende qué necesita y llama a " +
            "`analizar_requerimiento`.",
        )
      }
      // `confirmed` is the model's reading of the answer; `explicitConfirmation` reads the
      // transcription of what was actually said. Requiring both to agree means a mis-heard
      // yes cannot open a case on its own.
      const turn = await callbacks.resolveSpokenText()
      const detected = turn === null ? null : explicitConfirmation(turn.text)
      if (turn === null || detected === null || detected !== confirmed) {
        // Spent even though it was rejected: this was the answer to a question the kiosk
        // did ask, it just was not a clear one. Leaving it unspent would glue it onto the
        // next answer, and "no sé" followed by "sí" reads as a no.
        turn?.commit()
        return errorToolOutput(
          "No quedó claro si te dijo que sí o que no. Vuelve a preguntárselo con tus " +
            "palabras, pidiendo una respuesta clara.",
        )
      }
      try {
        const response = await callbacks.confirmRequirement(
          detected,
          details?.toolCall?.callId,
        )
        turn.commit()
        return flowToolOutput(response)
      } catch {
        return errorToolOutput(
          "No pudiste registrar la respuesta. Discúlpate brevemente y dile que lo intente " +
            "otra vez o que pida ayuda a un ejecutivo.",
        )
      }
    },
  })

  return new RealtimeAgent({
    name: "Asistente virtual del kiosco",
    // Both come from the client secret the backend minted, which is the only copy of the
    // persona. The Agents SDK sends these as the session instructions on connect, so a
    // second copy written here would be the one that actually took effect -- see
    // KIOSK_VOICE_INSTRUCTIONS in backend/app/services/openai_provider.py.
    voice: options.voice,
    instructions: options.instructions,
    tools: [analyzeRequirement, confirmRequirement],
  })
}
