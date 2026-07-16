import Link from 'next/link'
import { Clock, ArrowRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import type { Ticket } from '@/lib/mock-data'

interface TicketCardProps {
  ticket: Ticket
}

export function TicketCard({ ticket }: TicketCardProps) {
  return (
    <Card className="hover:shadow-md hover:border-[#1168BD]/20 transition-all duration-200">
      <div className="p-5">
        <div className="flex items-start justify-between gap-4">
          {/* Left: ticket number + summary */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono font-bold text-[#1168BD] bg-[#1168BD]/8 px-2 py-0.5 rounded-md">
                #{ticket.number}
              </span>
              <Badge variant={ticket.category} />
              <Badge variant={ticket.priority} />
            </div>
            <p className="text-gray-800 text-sm font-medium line-clamp-2 leading-snug">
              {ticket.summary}
            </p>
            <div className="flex items-center gap-4 mt-3">
              <span className="flex items-center gap-1.5 text-xs text-gray-400">
                <Clock className="w-3.5 h-3.5" />
                Asignado a las {ticket.timeAssigned} — hace {ticket.minutesElapsed} min
              </span>
            </div>
          </div>

          {/* Right: action */}
          <Link
            href={`/ejecutivo/caso/${ticket.id}`}
            className="shrink-0 flex items-center gap-1.5 text-sm font-semibold text-[#1168BD] hover:text-[#0d56a0] bg-[#1168BD]/8 hover:bg-[#1168BD]/15 px-4 py-2 rounded-xl transition-all"
          >
            Ver detalle
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </Card>
  )
}
