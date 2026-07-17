"use client"

import { StatusSelector } from "@/components/executive/status-selector"
import { useAuth } from "@/components/providers/auth-provider"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { errorMessage } from "@/lib/api"
import { formatDateTime } from "@/lib/labels"
import type { TicketDetail } from "@/lib/types"
import { ArrowLeft, Clock, Shield, User } from "lucide-react"
import Link from "next/link"
import { use, useCallback, useEffect, useState } from "react"

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
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

  useEffect(() => {
    queueMicrotask(() => void load())
  }, [load])

  if (error && !ticket) {
    return (
      <div className="mx-auto max-w-3xl">
        <Link className="text-sm text-[#1168BD]" href="/ejecutivo">
          ← Volver
        </Link>
        <p className="mt-5 rounded-xl bg-red-50 p-4 text-red-700">{error}</p>
      </div>
    )
  }
  if (!ticket) return <p className="text-center text-gray-500">Cargando caso…</p>

  return (
    <div className="mx-auto max-w-4xl">
      <Link
        className="mb-6 inline-flex items-center gap-2 text-sm text-gray-500 transition hover:text-[#1168BD]"
        href="/ejecutivo"
      >
        <ArrowLeft className="h-4 w-4" />
        Volver a casos asignados
      </Link>

      <div className="mb-6">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold text-gray-900">Ticket #{ticket.number}</h1>
          <Badge variant={ticket.category} />
          <Badge variant={ticket.priority} />
        </div>
        <p className="text-gray-600">{ticket.summary}</p>
      </div>

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Card>
          <CardContent className="py-4">
            <p className="text-xs uppercase tracking-widest text-gray-400">Sesión protegida</p>
            <p className="mt-2 font-mono font-semibold text-gray-800">
              {ticket.client_session_id}
            </p>
            <p className="mt-1 text-xs text-gray-400">{ticket.identification_status}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs uppercase tracking-widest text-gray-400">Tiempo de espera</p>
            <p className="mt-2 flex items-center gap-2 font-semibold text-gray-800">
              <Clock className="h-4 w-4 text-[#1168BD]" />
              {ticket.wait_time_min} min
            </p>
            {ticket.preferential_attention && (
              <p className="mt-1 text-xs font-semibold text-purple-600">Atención preferente</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs uppercase tracking-widest text-gray-400">Ejecutivo</p>
            <p className="mt-2 flex items-center gap-2 font-semibold text-gray-800">
              <User className="h-4 w-4 text-[#1168BD]" />
              {ticket.executive_name ?? "Pendiente"}
            </p>
            <p className="mt-1 text-xs text-gray-400">{ticket.window_number ?? "Sin ventanilla"}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Trazabilidad del caso</CardTitle>
          </CardHeader>
          <CardContent>
            {ticket.events.length === 0 ? (
              <p className="text-sm text-gray-500">Aún no existen eventos.</p>
            ) : (
              <ol className="space-y-5">
                {ticket.events.map((event) => (
                  <li className="flex items-start gap-4" key={event.id}>
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#1168BD]/10 text-[#1168BD]">
                      <Shield className="h-4 w-4" />
                    </span>
                    <div>
                      <p className="text-sm font-medium text-gray-800">{event.description}</p>
                      <p className="mt-1 text-xs text-gray-400">
                        {formatDateTime(event.created_at)}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Gestión de estado</CardTitle>
            </CardHeader>
            <CardContent>
              <StatusSelector ticket={ticket} onUpdated={setTicket} />
            </CardContent>
          </Card>
          <Card>
            <CardContent>
              <p className="text-xs uppercase tracking-widest text-gray-400">Perfil asignado</p>
              <p className="mt-2 font-semibold text-gray-900">
                {ticket.executive_title ?? "Sin especialidad asignada"}
              </p>
              <p className="mt-1 text-sm text-gray-500">
                Nivel de consulta: {ticket.consultation_level}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
