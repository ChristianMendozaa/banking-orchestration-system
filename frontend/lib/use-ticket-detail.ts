"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { errorMessage } from "@/lib/api"
import type { TicketDetail } from "@/lib/types"
import { useCallback, useEffect, useState } from "react"

export function useTicketDetail(id: string) {
  const { request } = useAuth()
  const [ticket, setTicket] = useState<TicketDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setTicket(await request<TicketDetail>(`/tickets/${encodeURIComponent(id)}`))
      setError(null)
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }, [id, request])

  useEffect(() => {
    queueMicrotask(() => void reload())
  }, [reload])

  return { ticket, setTicket, error, setError, reload }
}
