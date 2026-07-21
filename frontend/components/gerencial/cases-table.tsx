import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { formatDateTime, resolutionLabels, statusLabels } from "@/lib/labels"
import type { ManagerialCase, TicketStatus } from "@/lib/types"

const statusDot: Record<TicketStatus, string> = {
  PENDIENTE: "bg-amber-400",
  EN_ATENCION: "bg-blue-500",
  CERRADO: "bg-emerald-500",
}

export function CasesTable({ cases }: { cases: ManagerialCase[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[920px] text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs uppercase tracking-widest text-gray-400">
            <th className="px-4 py-3 font-medium">Caso</th>
            <th className="px-4 py-3 font-medium">Prioridad</th>
            <th className="px-4 py-3 font-medium">Ejecutivo</th>
            <th className="px-4 py-3 font-medium">Estado</th>
            <th className="px-4 py-3 font-medium">Tiempos</th>
            <th className="px-4 py-3 font-medium">Resultado</th>
            <th className="px-4 py-3"><span className="sr-only">Abrir</span></th>
          </tr>
        </thead>
        <tbody>
          {cases.map((row) => (
            <tr className="border-b border-gray-50 transition hover:bg-blue-50/40" key={row.id}>
              <td className="max-w-xs px-4 py-3">
                <Link className="font-mono font-bold text-[#1168BD] hover:underline" href={`/gerencial/casos/${row.id}`}>{row.ticket}</Link>
                <p className="mt-1 line-clamp-1 text-xs text-gray-600">{row.summary}</p>
                <p className="mt-1 text-[11px] text-gray-400">{formatDateTime(row.created_at)}</p>
              </td>
              <td className="px-4 py-3"><div className="flex flex-col items-start gap-1"><Badge variant={row.priority} /><Badge variant={row.category} /></div></td>
              <td className="px-4 py-3 text-gray-700">{row.executive ?? "Sin asignar"}</td>
              <td className="px-4 py-3"><span className="flex items-center gap-2 text-gray-600"><span className={`h-2 w-2 rounded-full ${statusDot[row.status]}`} />{statusLabels[row.status]}</span></td>
              <td className="px-4 py-3 text-xs text-gray-500"><p>Espera: {row.wait_time_min} min</p><p className="mt-1">Atención: {row.attention_time_min === null ? "—" : `${row.attention_time_min} min`}</p></td>
              <td className="px-4 py-3 text-gray-600">{row.resolution_outcome ? resolutionLabels[row.resolution_outcome] : "—"}</td>
              <td className="px-4 py-3"><Link aria-label={`Abrir ${row.ticket}`} className="grid h-9 w-9 place-items-center rounded-lg text-[#1168BD] hover:bg-[#1168BD]/10" href={`/gerencial/casos/${row.id}`}><ArrowRight className="h-4 w-4" /></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
      {cases.length === 0 && <p className="p-10 text-center text-gray-400">No existen casos para los filtros seleccionados.</p>}
    </div>
  )
}
