import { Badge } from "@/components/ui/badge"
import { statusLabels } from "@/lib/labels"
import type { ManagerialCase, TicketStatus } from "@/lib/types"

const statusDot: Record<TicketStatus, string> = {
  PENDIENTE: "bg-yellow-400",
  EN_ATENCION: "bg-blue-500",
  CERRADO: "bg-green-500",
}

export function CasesTable({ cases }: { cases: ManagerialCase[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs uppercase tracking-widest text-gray-400">
            <th className="px-4 py-3 font-medium">Ticket</th>
            <th className="px-4 py-3 font-medium">Categoría</th>
            <th className="px-4 py-3 font-medium">Prioridad</th>
            <th className="px-4 py-3 font-medium">Ejecutivo</th>
            <th className="px-4 py-3 font-medium">Estado</th>
            <th className="px-4 py-3 font-medium">Tiempo</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((row) => (
            <tr className="border-b border-gray-50 hover:bg-gray-50" key={row.ticket}>
              <td className="px-4 py-3 font-mono font-bold text-[#1168BD]">{row.ticket}</td>
              <td className="px-4 py-3"><Badge variant={row.category} /></td>
              <td className="px-4 py-3"><Badge variant={row.priority} /></td>
              <td className="px-4 py-3 text-gray-700">{row.executive ?? "Sin asignar"}</td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-2 text-gray-600">
                  <span className={`h-2 w-2 rounded-full ${statusDot[row.status]}`} />
                  {statusLabels[row.status]}
                </span>
              </td>
              <td className="px-4 py-3 font-mono text-gray-500">
                {row.attention_time_min === null ? "—" : `${row.attention_time_min} min`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {cases.length === 0 && <p className="p-8 text-center text-gray-400">Sin casos en el período.</p>}
    </div>
  )
}
