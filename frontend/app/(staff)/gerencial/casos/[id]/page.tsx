"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { errorMessage } from "@/lib/api"
import { formatDateTime, resolutionLabels, statusLabels } from "@/lib/labels"
import type { TicketDetail } from "@/lib/types"
import { Activity, ArrowLeft, Clock3, IdCard, MessageSquareText, ShieldCheck, UserRound } from "lucide-react"
import Link from "next/link"
import { use, useCallback, useEffect, useState } from "react"

export default function ManagerCasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const { request } = useAuth()
  const [ticket, setTicket] = useState<TicketDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setTicket(await request<TicketDetail>(`/tickets/${encodeURIComponent(id)}`))
      setError(null)
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }, [id, request])

  useEffect(() => { queueMicrotask(() => void load()) }, [load])

  if (error && !ticket) return <div className="mx-auto max-w-5xl"><Link className="text-sm text-[#1168BD]" href="/gerencial">← Volver al panel</Link><p className="mt-5 rounded-xl bg-red-50 p-4 text-red-700">{error}</p></div>
  if (!ticket) return <div className="mx-auto h-80 max-w-5xl animate-pulse rounded-2xl bg-white" aria-label="Cargando expediente" />

  return (
    <div className="mx-auto max-w-6xl">
      <Link className="mb-5 inline-flex items-center gap-2 text-sm text-gray-500 hover:text-[#1168BD]" href="/gerencial"><ArrowLeft className="h-4 w-4" />Volver al panel gerencial</Link>
      <div className="mb-6 rounded-2xl bg-[#0A1628] p-6 text-white shadow-lg">
        <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm text-white/55">Ticket #{ticket.number}</span><span className="rounded-full bg-white/10 px-3 py-1 text-xs font-semibold">{statusLabels[ticket.status]}</span></div>
        <h1 className="mt-3 max-w-4xl text-2xl font-bold">{ticket.summary}</h1>
        <div className="mt-4 flex flex-wrap gap-2"><Badge variant={ticket.category} /><Badge variant={ticket.priority} /></div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.7fr)]">
        <div className="space-y-6">
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><MessageSquareText className="h-5 w-5 text-[#1168BD]" />Conversación enmascarada</CardTitle></CardHeader><CardContent>
            {ticket.conversation.length === 0 ? <p className="rounded-xl bg-gray-50 p-5 text-sm text-gray-500">No existe conversación persistida para este caso histórico.</p> : <ol className="space-y-4">{ticket.conversation.map((message) => <li className={`flex ${message.role === "CUSTOMER" ? "justify-end" : "justify-start"}`} key={message.id}><div className={`max-w-[85%] rounded-2xl px-4 py-3 ${message.role === "CUSTOMER" ? "bg-[#1168BD] text-white" : "bg-gray-100 text-gray-800"}`}><p className={`text-xs font-semibold ${message.role === "CUSTOMER" ? "text-white/60" : "text-gray-400"}`}>{message.role === "CUSTOMER" ? "Cliente" : "Asistente"}</p><p className="mt-1 text-sm leading-relaxed">{message.text}</p><p className={`mt-2 text-[11px] ${message.role === "CUSTOMER" ? "text-white/50" : "text-gray-400"}`}>{formatDateTime(message.created_at)}</p></div></li>)}</ol>}
          </CardContent></Card>
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><Activity className="h-5 w-5 text-[#1168BD]" />Trazabilidad</CardTitle></CardHeader><CardContent><ol className="space-y-5">{ticket.events.map((event) => <li className="flex items-start gap-3" key={event.id}><span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#1168BD]/10 text-[#1168BD]"><ShieldCheck className="h-4 w-4" /></span><div><p className="text-sm font-medium text-gray-800">{event.description}</p><p className="mt-1 text-xs text-gray-400">{formatDateTime(event.created_at)}</p></div></li>)}</ol></CardContent></Card>
        </div>

        <aside className="space-y-6">
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><UserRound className="h-5 w-5 text-[#1168BD]" />Datos protegidos</CardTitle></CardHeader><CardContent className="space-y-4"><div><p className="text-xs uppercase tracking-widest text-gray-400">Identificación</p><p className="mt-1 text-sm font-semibold text-gray-800">{ticket.identity.status.replaceAll("_", " ")}</p></div><div><p className="text-xs uppercase tracking-widest text-gray-400">CI enmascarado</p><p className="mt-1 flex items-center gap-2 font-mono font-bold text-gray-800"><IdCard className="h-4 w-4 text-[#1168BD]" />{ticket.identity.masked_identifier ?? "No requerido"}</p></div><p className="text-xs text-gray-400">El CI completo está restringido al ejecutivo asignado.</p></CardContent></Card>
          <Card><CardHeader><CardTitle>Operación</CardTitle></CardHeader><CardContent className="space-y-4"><div><p className="text-xs uppercase tracking-widest text-gray-400">Ejecutivo</p><p className="mt-1 font-semibold text-gray-900">{ticket.executive_name ?? "Sin asignar"}</p><p className="text-xs text-gray-500">{ticket.executive_title}</p></div><div><p className="text-xs uppercase tracking-widest text-gray-400">Espera</p><p className="mt-1 flex items-center gap-2 font-semibold"><Clock3 className="h-4 w-4 text-[#1168BD]" />{ticket.wait_time_min} min</p></div><div><p className="text-xs uppercase tracking-widest text-gray-400">Nivel</p><p className="mt-1 text-sm text-gray-700">{ticket.consultation_level}</p></div></CardContent></Card>
          <Card><CardHeader><CardTitle>Resultado</CardTitle></CardHeader><CardContent>{ticket.resolution_outcome ? <><p className="font-semibold text-gray-900">{resolutionLabels[ticket.resolution_outcome]}</p><p className="mt-2 text-sm leading-relaxed text-gray-600">{ticket.resolution_note}</p></> : <p className="text-sm text-gray-500">El caso todavía no tiene un cierre documentado.</p>}</CardContent></Card>
        </aside>
      </div>
    </div>
  )
}
