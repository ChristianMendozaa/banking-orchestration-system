"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { resolutionLabels } from "@/lib/labels"
import type { ResolutionOutcome, TicketDetail } from "@/lib/types"
import { CheckCircle2, PlayCircle } from "lucide-react"
import { useState } from "react"

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
  const [outcome, setOutcome] = useState<ResolutionOutcome>("RESUELTO")
  const [note, setNote] = useState("")

  async function update(status: "EN_ATENCION" | "CERRADO") {
    setUpdating(true)
    setError(null)
    try {
      const response = await request<TicketDetail>(`/tickets/${ticket.id}/status`, {
        method: "PATCH",
        body: JSON.stringify({
          status,
          expected_version: ticket.version,
          resolution_outcome: status === "CERRADO" ? outcome : undefined,
          resolution_note: status === "CERRADO" ? note : undefined,
        }),
      })
      onUpdated(response)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setUpdating(false)
    }
  }

  if (ticket.status === "CERRADO") {
    return (
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
        <p className="flex items-center gap-2 font-semibold text-emerald-800">
          <CheckCircle2 className="h-5 w-5" /> Caso cerrado
        </p>
        <p className="mt-1 text-sm text-emerald-700">
          {ticket.resolution_outcome ? resolutionLabels[ticket.resolution_outcome] : "Sin resultado histórico registrado"}
        </p>
      </div>
    )
  }

  if (ticket.status === "PENDIENTE") {
    return (
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Al iniciar este caso quedará marcado como tu única atención activa.
        </p>
        <Button disabled={updating} onClick={() => void update("EN_ATENCION")}>
          <PlayCircle className="h-4 w-4" />
          {updating ? "Iniciando…" : "Iniciar atención"}
        </Button>
        {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="text-sm font-semibold text-gray-800" htmlFor="resolution-outcome">Resultado de la atención</label>
        <select
          className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-[#1168BD] focus:ring-2 focus:ring-[#1168BD]/15"
          id="resolution-outcome"
          onChange={(event) => setOutcome(event.target.value as ResolutionOutcome)}
          value={outcome}
        >
          {(Object.entries(resolutionLabels) as [ResolutionOutcome, string][]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      <div>
        <label className="text-sm font-semibold text-gray-800" htmlFor="resolution-note">Nota de cierre</label>
        <textarea
          className="mt-2 min-h-28 w-full resize-y rounded-xl border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-[#1168BD] focus:ring-2 focus:ring-[#1168BD]/15"
          id="resolution-note"
          maxLength={1000}
          minLength={10}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Describe brevemente qué se hizo y qué debe ocurrir después."
          value={note}
        />
        <p className="mt-1 text-right text-xs text-gray-400">{note.length}/1000</p>
      </div>
      <Button disabled={updating || note.trim().length < 10} onClick={() => void update("CERRADO")}>
        <CheckCircle2 className="h-4 w-4" />
        {updating ? "Cerrando…" : "Cerrar caso"}
      </Button>
      {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
      <p className="text-xs text-gray-400">La nota se protege nuevamente antes de guardarse.</p>
    </div>
  )
}
