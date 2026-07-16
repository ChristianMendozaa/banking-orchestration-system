import { tickets, timelineEvents } from '@/lib/mock-data'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusSelector } from '@/components/executive/status-selector'
import { ArrowLeft, Clock, Shield, User } from 'lucide-react'
import Link from 'next/link'

export default async function CasoDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const ticket = tickets.find((t) => t.id === id) ?? tickets[0]

  return (
    <div className="max-w-3xl mx-auto">
      {/* Back link */}
      <Link
        href="/ejecutivo"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-[#1168BD] mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Volver a casos activos
      </Link>

      {/* Case header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <span className="text-2xl font-bold text-gray-900">Ticket #{ticket.number}</span>
            <Badge variant={ticket.category} />
            <Badge variant={ticket.priority} />
          </div>
          <p className="text-gray-600">{ticket.summary}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        {/* Session ID */}
        <Card>
          <CardContent className="py-4">
            <p className="text-xs uppercase tracking-widest text-gray-400 mb-1">Sesión del cliente</p>
            <p className="font-mono font-semibold text-gray-800">{ticket.clientSessionId}</p>
            <p className="text-xs text-gray-400 mt-1">Datos anonimizados</p>
          </CardContent>
        </Card>
        {/* Wait time */}
        <Card>
          <CardContent className="py-4">
            <p className="text-xs uppercase tracking-widest text-gray-400 mb-1">Tiempo de espera</p>
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#1168BD]" />
              <p className="font-semibold text-gray-800">{ticket.waitTimeMin} min</p>
            </div>
          </CardContent>
        </Card>
        {/* Assigned executive */}
        <Card>
          <CardContent className="py-4">
            <p className="text-xs uppercase tracking-widest text-gray-400 mb-1">Ejecutivo asignado</p>
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-[#1168BD]" />
              <p className="font-semibold text-gray-800 text-sm">{ticket.executiveName}</p>
            </div>
            <p className="text-xs text-gray-400 mt-1">{ticket.windowNumber}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Timeline */}
        <Card>
          <CardHeader>
            <CardTitle>Trazabilidad del caso</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="relative">
              {/* Vertical connector line */}
              <div className="absolute left-4 top-4 bottom-4 w-px bg-gray-100" />

              <ul className="flex flex-col gap-5">
                {timelineEvents.map((event, idx) => (
                  <li key={event.id} className="flex items-start gap-4 relative">
                    <div
                      className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10 ${
                        idx === timelineEvents.length - 1
                          ? 'bg-[#1168BD] text-white'
                          : 'bg-gray-100 text-gray-400'
                      }`}
                    >
                      <Shield className="w-4 h-4" />
                    </div>
                    <div className="pt-1 min-w-0">
                      <p className="text-sm text-gray-800 font-medium leading-snug">{event.description}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{event.time}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>

        {/* Status management */}
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle>Gestión de estado</CardTitle>
            </CardHeader>
            <CardContent>
              <StatusSelector initialStatus={ticket.status} />
            </CardContent>
          </Card>

          {/* Executive specialty */}
          <Card>
            <CardContent className="py-4">
              <p className="text-xs uppercase tracking-widest text-gray-400 mb-3">Especialidad</p>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-[#1168BD]/10 flex items-center justify-center">
                  <Shield className="w-5 h-5 text-[#1168BD]" />
                </div>
                <div>
                  <p className="font-semibold text-gray-900 text-sm">{ticket.executiveTitle}</p>
                  <p className="text-xs text-gray-400">{ticket.executiveName}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
