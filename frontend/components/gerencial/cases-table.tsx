import { managerialCases } from '@/lib/mock-data'
import { Badge } from '@/components/ui/badge'
import type { Status } from '@/lib/mock-data'

const statusDot: Record<Status, string> = {
  PENDIENTE: 'bg-yellow-400',
  EN_ATENCION: 'bg-blue-500',
  CERRADO: 'bg-green-500',
}

const statusLabel: Record<Status, string> = {
  PENDIENTE: 'Pendiente',
  EN_ATENCION: 'En Atención',
  CERRADO: 'Cerrado',
}

export function CasesTable() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="text-left px-4 py-3 text-xs uppercase tracking-widest text-gray-400 font-medium rounded-tl-xl">Ticket</th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-widest text-gray-400 font-medium">Categoría</th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-widest text-gray-400 font-medium">Prioridad</th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-widest text-gray-400 font-medium">Ejecutivo</th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-widest text-gray-400 font-medium">Estado</th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-widest text-gray-400 font-medium rounded-tr-xl">Tiempo atención</th>
          </tr>
        </thead>
        <tbody>
          {managerialCases.map((row, idx) => (
            <tr
              key={row.ticket}
              className={`border-b border-gray-50 hover:bg-gray-50/60 transition-colors ${
                idx % 2 === 0 ? '' : 'bg-gray-50/30'
              }`}
            >
              <td className="px-4 py-3">
                <span className="font-mono font-bold text-[#1168BD]">{row.ticket}</span>
              </td>
              <td className="px-4 py-3">
                <Badge variant={row.category} />
              </td>
              <td className="px-4 py-3">
                <Badge variant={row.priority} />
              </td>
              <td className="px-4 py-3 text-gray-700">{row.executive}</td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${statusDot[row.status]}`} />
                  <span className="text-gray-600">{statusLabel[row.status]}</span>
                </span>
              </td>
              <td className="px-4 py-3 text-gray-500 font-mono">{row.attentionTime}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
