import { tickets } from '@/lib/mock-data'
import { TicketCard } from '@/components/executive/ticket-card'

export default function EjecutivoPage() {
  const criticalCount = tickets.filter((t) => t.priority === 'CRITICO').length
  const inProgressCount = tickets.filter((t) => t.status === 'EN_ATENCION').length

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Casos Activos</h1>
          <p className="text-gray-500 text-sm mt-0.5">
            {tickets.length} casos asignados · {inProgressCount} en atención · {criticalCount} crítico(s)
          </p>
        </div>
        <div className="flex items-center gap-2">
          {criticalCount > 0 && (
            <span className="flex items-center gap-1.5 bg-red-100 text-red-700 px-3 py-1.5 rounded-xl text-sm font-semibold">
              <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              {criticalCount} Crítico(s)
            </span>
          )}
        </div>
      </div>

      {/* Ticket list */}
      <div className="flex flex-col gap-3">
        {tickets.map((ticket) => (
          <TicketCard key={ticket.id} ticket={ticket} />
        ))}
      </div>
    </div>
  )
}
