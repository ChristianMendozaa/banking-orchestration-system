"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import type { TicketDetail } from "@/lib/types"
import { Eye, EyeOff, IdCard } from "lucide-react"
import { useEffect, useState } from "react"

export function IdentifierReveal({
  ticket,
  onError,
  onRevealed,
}: {
  ticket: TicketDetail
  onError: (message: string | null) => void
  onRevealed: () => Promise<void>
}) {
  const { request } = useAuth()
  const [revealedCi, setRevealedCi] = useState<string | null>(null)
  const [revealing, setRevealing] = useState(false)
  useEffect(() => {
    if (!revealedCi) return
    const timer = window.setTimeout(() => setRevealedCi(null), 30_000)
    return () => window.clearTimeout(timer)
  }, [revealedCi])

  // The backend only reveals during active attention, so the button is offered only then
  // and a revealed value does not outlive the attention it was revealed for.
  const attending = ticket.status === "EN_ATENCION"
  const visibleCi = attending ? revealedCi : null

  async function revealIdentifier() {
    setRevealing(true)
    onError(null)
    try {
      const response = await request<{ identifier: string }>(`/tickets/${ticket.id}/identifier/reveal`, { method: "POST" })
      setRevealedCi(response.identifier)
      await onRevealed()
    } catch (reason) {
      onError(errorMessage(reason))
    } finally {
      setRevealing(false)
    }
  }

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">Cédula de identidad</p>
      <p className="mt-2 flex items-center gap-2 font-mono text-lg font-bold text-gray-900"><IdCard className="h-5 w-5 text-[#1168BD]" />{visibleCi ?? ticket.identity.masked_identifier ?? "No requerida"}</p>
      {ticket.identity.reveal_available && attending && (
        <Button className="mt-2" disabled={revealing} onClick={() => visibleCi ? setRevealedCi(null) : void revealIdentifier()} size="sm" variant="secondary">
          {visibleCi ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          {visibleCi ? "Ocultar CI" : revealing ? "Revelando…" : "Revelar por 30 s"}
        </Button>
      )}
      {ticket.identity.reveal_available && ticket.status === "PENDIENTE" && <p className="mt-2 text-xs text-gray-400">Inicia la atención para revelar el CI completo.</p>}
      {!ticket.identity.reveal_available && ticket.identity.masked_identifier && <p className="mt-2 text-xs text-gray-400">CI completo no disponible para este caso histórico.</p>}
    </div>
  )
}
