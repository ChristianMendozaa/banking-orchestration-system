import { RealtimeAgent, tool } from "@openai/agents/realtime"
import { z } from "zod"

import {
  errorToolOutput,
  turnProcessingToolOutput,
  type KioskRealtimeCallbacks,
  type KioskTurnProcessingResult,
} from "@/lib/kiosk-realtime"

export function createKioskRealtimeAgent(
  callbacks: KioskRealtimeCallbacks,
  options: { instructions: string; voice: string },
): RealtimeAgent {
  // Everything the tool hands back goes through here, so the application always gets to
  // settle `tool_choice` and the speaking floor before the SDK creates the response that
  // speaks it. Doing this from `agent_tool_end` was too late: that event fires after
  // `response.create` is already on the wire.
  const finish = (result: KioskTurnProcessingResult): Record<string, unknown> => {
    callbacks.settleTurn(result)
    return turnProcessingToolOutput(result)
  }

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
    // Without these the SDK hands the persona its own English strings -- "Tool
    // 'procesar_turno' timed out after 25000ms.", "An error occurred while running the
    // tool." -- in place of a result, with none of the fields the instructions are written
    // around. The customer heard the model improvise around them.
    timeoutErrorFunction: () =>
      JSON.stringify(
        errorToolOutput(
          "La consulta se está demorando más de lo normal. Dilo en una frase y pregúntale " +
            "si prefiere esperar o que la atienda un ejecutivo.",
        ),
      ),
    errorFunction: () =>
      JSON.stringify(
        errorToolOutput(
          "No pudiste consultar el sistema. Discúlpate brevemente y dile que lo intente " +
            "otra vez o que pida ayuda a un ejecutivo.",
        ),
      ),
    async execute(_args, _context, details) {
      // A result the application is holding outweighs anything that was said: the identity
      // card is typed on a form, so the turn that produced this outcome never passed
      // through speech and there is nothing to transcribe.
      const pending = callbacks.takePendingResult()
      if (pending) return finish(pending)

      const turn = await callbacks.resolveSpokenText()
      if (!turn) {
        // Not a failure. The model calls this tool once per customer turn, but it also
        // calls it when it is simply checking in -- after a barge-in that produced no
        // words, while the person is typing their CI, right after a flow already closed.
        // Answering "you do not have what they said, ask them to repeat" turned every one
        // of those into the kiosk apologising for a problem that did not exist.
        return finish({ kind: "noop" })
      }
      try {
        const result = await callbacks.processSpokenTurn(
          turn.text,
          details?.toolCall?.callId,
          // The SDK merges its own timeout into this signal, so handing it to `fetch` is
          // what makes an abandoned turn stop mutating state behind the conversation.
          details?.signal,
        )
        // A backend failure leaves the words available for retry. An ambiguous confirmation
        // is a successful retry result and is spent so it cannot bleed into the next answer.
        // A state-conflict `noop` is not a result either: nothing looked at those words, so
        // spending them here would delete the only copy of what the person said.
        if (result.kind !== "noop") turn.commit()
        else turn.release()
        return finish(result)
      } catch {
        turn.release()
        // Only a genuine outage reaches here: `processSpokenTurn` resolves the kiosk's own
        // state disagreements itself and returns an idle result rather than throwing, so
        // this apology is no longer the catch-all it used to be.
        callbacks.settleTurn({ kind: "retry", guidance: "" })
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
