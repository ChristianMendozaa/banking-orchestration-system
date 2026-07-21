import Link from "next/link"
import { ArrowRight, Clock3, IdCard, UserRound } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { statusLabels } from "@/lib/labels"
import type { TicketListItem, TicketStatus } from "@/lib/types"

const statusStyles: Record<TicketStatus, string> = {
  PENDIENTE: "border-amber-200 bg-amber-50 text-amber-800",
  EN_ATENCION: "border-blue-200 bg-blue-50 text-blue-800",
  CERRADO: "border-emerald-200 bg-emerald-50 text-emerald-800",
}

export function TicketCard({ ticket }: { ticket: TicketListItem }) {
  return (
    <Card
      className={`transition hover:-translate-y-0.5 hover:border-[#1168BD]/25 hover:shadow-md ${
        ticket.status === "EN_ATENCION" ? "border-[#1168BD]/40 ring-2 ring-[#1168BD]/10" : ""
      }`}
    >
      <div className="p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-[#1168BD]/8 px-2 py-0.5 font-mono text-xs font-bold text-[#1168BD]">
                #{ticket.number}
              </span>
              <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${statusStyles[ticket.status]}`}>
                {statusLabels[ticket.status]}
              </span>
              <Badge variant={ticket.priority} />
              <Badge variant={ticket.category} />
            </div>

            <p className="line-clamp-2 text-sm font-semibold leading-snug text-gray-900">
              {ticket.summary}
            </p>

            <div className="mt-4 grid gap-2 text-xs text-gray-500 sm:grid-cols-3">
              <span className="flex items-center gap-1.5">
                <UserRound className="h-3.5 w-3.5 text-gray-400" />
                {ticket.client_display_name ?? "Cliente sin registro"}
              </span>
              <span className="flex items-center gap-1.5 font-mono">
                <IdCard className="h-3.5 w-3.5 text-gray-400" />
                {ticket.masked_identifier ?? "CI no requerido"}
              </span>
              <span className="flex items-center gap-1.5">
                <Clock3 className="h-3.5 w-3.5 text-gray-400" />
                {ticket.status === "PENDIENTE"
                  ? `${ticket.wait_time_min} min en espera`
                  : ticket.status === "EN_ATENCION"
                    ? `${ticket.minutes_elapsed} min asignado`
                    : "Atención finalizada"}
              </span>
            </div>
          </div>

          <Link
            className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl bg-[#1168BD]/8 px-4 py-2 text-sm font-semibold text-[#1168BD] transition hover:bg-[#1168BD]/15 hover:text-[#0d56a0]"
            href={`/ejecutivo/caso/${ticket.id}`}
          >
            {ticket.status === "EN_ATENCION" ? "Continuar atención" : "Ver expediente"}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </Card>
  )
}
