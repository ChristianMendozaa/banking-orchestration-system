"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { statusLabels } from "@/lib/labels"
import type { TicketDetail, TicketStatus } from "@/lib/types"
import { CheckCircle2 } from "lucide-react"
import { useState } from "react"

const nextStatus: Record<TicketStatus, TicketStatus | null> = {
  PENDIENTE: "EN_ATENCION",
  EN_ATENCION: "CERRADO",
  CERRADO: null,
}

export function StatusSelector({
  ticket,
  onUpdated,
}: {
  ticket: TicketDetail
  onUpdated: (ticket: TicketDetail) => void
}) {
  const { request } = useAuth()
  const [updating, setUpdating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const next = nextStatus[ticket.status]

  async function update() {
    if (!next) return
    setUpdating(true)
    setError(null)
    try {
      const response = await request<TicketDetail>(`/tickets/${ticket.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: next, expected_version: ticket.version }),
      })
      onUpdated(response)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setUpdating(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm font-medium text-gray-700">Estado actual</p>
        <span className="mt-2 inline-flex rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700">
          {statusLabels[ticket.status]}
        </span>
      </div>
      {next ? (
        <Button disabled={updating} onClick={update}>
          <CheckCircle2 className="h-4 w-4" />
          {updating ? "Actualizando…" : `Marcar como ${statusLabels[next].toLowerCase()}`}
        </Button>
      ) : (
        <p className="text-sm text-green-700">El caso está cerrado y no admite más cambios.</p>
      )}
      {error && (
        <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
      <p className="text-xs text-gray-400">
        La transición se valida en el servidor y usa control de versión para evitar sobrescrituras.
      </p>
    </div>
  )
}
