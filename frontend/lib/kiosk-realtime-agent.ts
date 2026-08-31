import { RealtimeAgent, tool } from "@openai/agents/realtime"
import { z } from "zod"

import {
  errorToolOutput,
  turnProcessingToolOutput,
  type KioskRealtimeCallbacks,
} from "@/lib/kiosk-realtime"

export function createKioskRealtimeAgent(
  callbacks: KioskRealtimeCallbacks,
  options: { instructions: string; voice: string },
): RealtimeAgent {
  const processTurn = tool({
    name: "procesar_turno",
    description:
      "Procesa obligatoriamente el turno que la persona acaba de decir. La aplicación " +
      "elige, según el estado real, si debe analizar una petición, registrar una " +
      "confirmación o cerrar la conversación. No recibe parámetros: la aplicación adjunta " +
      "la transcripción oficial. Usa únicamente su resultado para responder.",
    // The model never retypes what it heard. The application attaches the session's own
    // Spanish transcription, avoiding corruption between speech and the backend.
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
        const result = await callbacks.processSpokenTurn(
          turn.text,
          details?.toolCall?.callId,
        )
        // A backend failure leaves the words available for retry. An ambiguous confirmation
        // is a successful retry result and is spent so it cannot bleed into the next answer.
        turn.commit()
        return turnProcessingToolOutput(result)
      } catch {
        return errorToolOutput(
          "No pudiste consultar el sistema. Discúlpate brevemente y dile que lo intente " +
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
    tools: [processTurn],
  })
}
