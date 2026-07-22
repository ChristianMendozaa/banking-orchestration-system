import { apiRequest } from "@/lib/api"
import type { KioskSession } from "@/lib/types"

export interface RealtimeSecret {
  value: string
  session?: {
    model?: string
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
