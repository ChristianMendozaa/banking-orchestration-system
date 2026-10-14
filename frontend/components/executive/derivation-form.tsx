"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { executiveStatusLabels } from "@/lib/labels"
import type {
  DerivationCandidate,
  DerivationCandidates,
  TicketDerivation,
  TicketDetail,
} from "@/lib/types"
import { Forward } from "lucide-react"
import { useState } from "react"

export function DerivationForm({
  ticket,
  onDerived,
}: {
  ticket: TicketDetail
  onDerived: (derivation: TicketDerivation) => void
}) {
  const { request } = useAuth()
  const [open, setOpen] = useState(false)
  const [candidates, setCandidates] = useState<DerivationCandidate[]>([])
  const [target, setTarget] = useState("")
  const [note, setNote] = useState("")
  const [deriving, setDeriving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function openForm() {
    setOpen(true)
    setError(null)
    try {
      const response = await request<DerivationCandidates>(
        `/tickets/${ticket.id}/derivation/candidates`,
      )
      setCandidates(response.items)
    } catch (reason) {
      // The automatic route does not need the list, so the form stays usable without it.
      setError(errorMessage(reason))
    }
  }

  async function derive() {
    setDeriving(true)
    setError(null)
    try {
      const response = await request<TicketDerivation>(`/tickets/${ticket.id}/derivation`, {
        method: "POST",
        body: JSON.stringify({
          expected_version: ticket.version,
          note,
          executive_id: target || null,
        }),
      })
      onDerived(response)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setDeriving(false)
    }
  }

  if (!open) {
    return (
      <Button onClick={() => void openForm()} size="sm" variant="secondary">
        <Forward className="h-4 w-4" />
        Derivar a otro ejecutivo
      </Button>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="text-sm font-semibold text-gray-800" htmlFor="derivation-target">Derivar a</label>
        <select
          className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-[#1168BD] focus:ring-2 focus:ring-[#1168BD]/15"
          id="derivation-target"
          onChange={(event) => setTarget(event.target.value)}
          value={target}
        >
          <option value="">Automático: mejor perfil para el caso</option>
          {candidates.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.name} · {candidate.window_number} · {executiveStatusLabels[candidate.status]} · {candidate.active_load} en cola
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-gray-400">Si el ejecutivo está en atención, el caso espera en su cola.</p>
      </div>
      <div>
        <label className="text-sm font-semibold text-gray-800" htmlFor="derivation-note">Motivo de la derivación</label>
        <textarea
          className="mt-2 min-h-24 w-full resize-y rounded-xl border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-[#1168BD] focus:ring-2 focus:ring-[#1168BD]/15"
          id="derivation-note"
          maxLength={1000}
          minLength={10}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Explica por qué se deriva y qué debe hacer quien reciba el caso."
          value={note}
        />
        <p className="mt-1 text-right text-xs text-gray-400">{note.length}/1000</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button disabled={deriving || note.trim().length < 10} onClick={() => void derive()} size="sm">
          <Forward className="h-4 w-4" />
          {deriving ? "Derivando…" : "Derivar caso"}
        </Button>
        <Button disabled={deriving} onClick={() => setOpen(false)} size="sm" variant="secondary">
          Cancelar
        </Button>
      </div>
      {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
    </div>
  )
}
