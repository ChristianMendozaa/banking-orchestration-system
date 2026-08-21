import { apiRequest } from "@/lib/api"
import type { KioskSession } from "@/lib/types"

export interface RealtimeSecret {
  value: string
  // The backend echoes the persona, model and voice it minted the secret with. The browser
  // builds its RealtimeAgent from these rather than holding a second copy -- see
  // KIOSK_VOICE_INSTRUCTIONS in backend/app/services/openai_provider.py.
  session?: {
    model?: string
    instructions?: string
    voice?: string
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
