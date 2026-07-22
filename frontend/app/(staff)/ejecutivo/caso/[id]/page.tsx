"use client"

import { StatusSelector } from "@/components/executive/status-selector"
import { useAuth } from "@/components/providers/auth-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { errorMessage } from "@/lib/api"
import { formatDateTime, resolutionLabels, statusLabels } from "@/lib/labels"
import { useTicketDetail } from "@/lib/use-ticket-detail"
import {
  Activity,
  ArrowLeft,
  Clock3,
  Eye,
  EyeOff,
  IdCard,
  MessageSquareText,
  ShieldCheck,
  UserRound,
} from "lucide-react"
import Link from "next/link"
import { use, useEffect, useState } from "react"

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const { request } = useAuth()
  const { ticket, setTicket, error, setError, reload } = useTicketDetail(id)
  const [revealedCi, setRevealedCi] = useState<string | null>(null)
  const [revealing, setRevealing] = useState(false)
  useEffect(() => {
    if (!revealedCi) return
    const timer = window.setTimeout(() => setRevealedCi(null), 30_000)
    return () => window.clearTimeout(timer)
  }, [revealedCi])

  async function revealIdentifier() {
    setRevealing(true)
    setError(null)
    try {
      const response = await request<{ identifier: string }>(`/tickets/${id}/identifier/reveal`, { method: "POST" })
      setRevealedCi(response.identifier)
      await reload()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setRevealing(false)
    }
  }

  if (error && !ticket) {
    return <div className="mx-auto max-w-4xl"><Link className="text-sm text-[#1168BD]" href="/ejecutivo">← Volver</Link><p className="mt-5 rounded-xl bg-red-50 p-4 text-red-700">{error}</p></div>
  }
  if (!ticket) return <div className="mx-auto h-80 max-w-5xl animate-pulse rounded-2xl bg-white" aria-label="Cargando expediente" />

  return (
    <div className="mx-auto max-w-6xl">
      <Link className="mb-5 inline-flex items-center gap-2 text-sm text-gray-500 transition hover:text-[#1168BD]" href="/ejecutivo">
        <ArrowLeft className="h-4 w-4" /> Volver a casos asignados
      </Link>

      <div className="mb-6 flex flex-col gap-4 rounded-2xl bg-[#0A1628] p-6 text-white shadow-lg sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-white/60">Ticket #{ticket.number}</span>
            <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-semibold">{statusLabels[ticket.status]}</span>
          </div>
          <h1 className="mt-3 max-w-3xl text-xl font-bold sm:text-2xl">{ticket.summary}</h1>
          <div className="mt-4 flex flex-wrap gap-2"><Badge variant={ticket.category} /><Badge variant={ticket.priority} /></div>
        </div>
        <div className="rounded-xl bg-white/10 px-4 py-3 text-sm">
          <p className="text-white/50">Tiempo de espera</p>
          <p className="mt-1 flex items-center gap-2 text-lg font-bold"><Clock3 className="h-5 w-5" />{ticket.wait_time_min} min</p>
        </div>
      </div>

      {error && <p className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.75fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><UserRound className="h-5 w-5 text-[#1168BD]" />Cliente</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">Nombre registrado</p>
                <p className="mt-2 font-semibold text-gray-900">{ticket.identity.display_name ?? "Cliente no registrado"}</p>
                <p className="mt-1 text-xs text-gray-500">{ticket.identity.status.replaceAll("_", " ")}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">Cédula de identidad</p>
                <p className="mt-2 flex items-center gap-2 font-mono text-lg font-bold text-gray-900"><IdCard className="h-5 w-5 text-[#1168BD]" />{revealedCi ?? ticket.identity.masked_identifier ?? "No requerida"}</p>
                {ticket.identity.reveal_available && (
                  <Button className="mt-2" disabled={revealing} onClick={() => revealedCi ? setRevealedCi(null) : void revealIdentifier()} size="sm" variant="secondary">
                    {revealedCi ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    {revealedCi ? "Ocultar CI" : revealing ? "Revelando…" : "Revelar por 30 s"}
                  </Button>
                )}
                {!ticket.identity.reveal_available && ticket.identity.masked_identifier && <p className="mt-2 text-xs text-gray-400">CI completo no disponible para este caso histórico.</p>}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><MessageSquareText className="h-5 w-5 text-[#1168BD]" />Conversación en el kiosco</CardTitle></CardHeader>
            <CardContent>
              {ticket.conversation.length === 0 ? (
                <div className="rounded-xl bg-gray-50 p-5 text-sm text-gray-500">El diálogo no está disponible para este caso. El resumen confirmado permanece visible arriba.</div>
              ) : (
                <ol className="space-y-4">
                  {ticket.conversation.map((message) => (
                    <li className={`flex ${message.role === "CUSTOMER" ? "justify-end" : "justify-start"}`} key={message.id}>
                      <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${message.role === "CUSTOMER" ? "bg-[#1168BD] text-white" : "bg-gray-100 text-gray-800"}`}>
                        <p className={`mb-1 text-xs font-semibold ${message.role === "CUSTOMER" ? "text-white/65" : "text-gray-400"}`}>{message.role === "CUSTOMER" ? "Cliente" : "Asistente"}</p>
                        <p className="text-sm leading-relaxed">{message.text}</p>
                        <p className={`mt-2 text-[11px] ${message.role === "CUSTOMER" ? "text-white/55" : "text-gray-400"}`}>{formatDateTime(message.created_at)}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="h-5 w-5 text-[#1168BD]" />Actividad del caso</CardTitle></CardHeader>
            <CardContent>
              <ol className="space-y-5">
                {ticket.events.map((event) => (
                  <li className="flex items-start gap-3" key={event.id}>
                    <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#1168BD]/10 text-[#1168BD]"><ShieldCheck className="h-4 w-4" /></span>
                    <div><p className="text-sm font-medium text-gray-800">{event.description}</p><p className="mt-1 text-xs text-gray-400">{formatDateTime(event.created_at)}</p></div>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Gestión del caso</CardTitle></CardHeader>
            <CardContent><StatusSelector ticket={ticket} onUpdated={setTicket} /></CardContent>
          </Card>
          <Card>
            <CardContent className="space-y-4">
              <div><p className="text-xs uppercase tracking-widest text-gray-400">Perfil asignado</p><p className="mt-1 font-semibold text-gray-900">{ticket.executive_title ?? "Sin especialidad"}</p></div>
              <div><p className="text-xs uppercase tracking-widest text-gray-400">Nivel de consulta</p><p className="mt-1 text-sm font-medium text-gray-700">{ticket.consultation_level}</p></div>
              <div><p className="text-xs uppercase tracking-widest text-gray-400">Sesión protegida</p><p className="mt-1 font-mono text-sm text-gray-600">{ticket.client_session_id}</p></div>
            </CardContent>
          </Card>
          {ticket.resolution_note && (
            <Card><CardHeader><CardTitle>Resolución</CardTitle></CardHeader><CardContent><p className="font-semibold text-gray-900">{ticket.resolution_outcome ? resolutionLabels[ticket.resolution_outcome] : "Sin resultado"}</p><p className="mt-2 text-sm leading-relaxed text-gray-600">{ticket.resolution_note}</p></CardContent></Card>
          )}
        </aside>
      </div>
    </div>
  )
}
