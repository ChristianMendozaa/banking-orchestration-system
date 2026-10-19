import { RealtimeAgent } from "@openai/agents/realtime"

// The agent has no tools. It used to carry one, `procesar_turno`, and decide by itself when
// to call it and when to answer -- which in a room full of people meant calling the bank
// before greeting anyone, prefacing every lookup with "Claro, déjame verificar...", and
// reading "no hay nada nuevo que procesar" aloud. The application now owns the turn: it
// waits for the transcription, asks the backend, and requests each response itself with that
// turn's instructions (see `turnInstructions` in lib/kiosk-realtime.ts).
export function createKioskRealtimeAgent(options: {
  instructions: string
  voice: string
}): RealtimeAgent {
  return new RealtimeAgent({
    name: "Asistente virtual del kiosco",
    // Both come from the client secret the backend minted, which is the only copy of the
    // persona. The Agents SDK sends these as the session instructions on connect, so a
    // second copy written here would be the one that actually took effect -- see
    // KIOSK_VOICE_INSTRUCTIONS in backend/app/services/prompts/voice.py.
    voice: options.voice,
    instructions: options.instructions,
    tools: [],
  })
}
