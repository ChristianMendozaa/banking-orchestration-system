import { apiRequest } from "@/lib/api"
import type { KioskSession } from "@/lib/types"

// The audio input configuration the secret was minted with, echoed back in the API's own
// snake_case. Declared as type aliases rather than interfaces so they stay assignable to the
// SDK's `RealtimeTurnDetectionConfig`, which is intersected with `Record<string, any>`.
type RealtimeTurnDetection = {
  type?: string
  eagerness?: "auto" | "low" | "medium" | "high"
  create_response?: boolean
  interrupt_response?: boolean
}

export type RealtimeAudioInput = {
  noise_reduction?: { type: string } | null
  transcription?: { model?: string; language?: string } | null
  turn_detection?: RealtimeTurnDetection | null
}

export interface RealtimeSecret {
  value: string
  // The backend echoes the persona, model, voice and audio input configuration it minted the
  // secret with. The browser builds its RealtimeAgent from these rather than holding a second
  // copy -- see KIOSK_VOICE_INSTRUCTIONS and create_realtime_client_secret in
  // backend/app/services/openai_provider.py.
  session?: {
    model?: string
    instructions?: string
    voice?: string
    audio_input?: RealtimeAudioInput
  } | null
}

export async function createKioskSession(
  preferentialAttention: boolean,
): Promise<KioskSession> {
  return apiRequest<KioskSession>("/kiosk/sessions", {
    method: "POST",
    body: JSON.stringify({ preferential_attention: preferentialAttention }),
  })
}

export async function kioskSessionRequest<T>(
  session: KioskSession,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set("X-Session-Token", session.session_token)
  return apiRequest<T>(`/kiosk/sessions/${session.session_id}${path}`, {
    ...init,
    headers,
  })
}
