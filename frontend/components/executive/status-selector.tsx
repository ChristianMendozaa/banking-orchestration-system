'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { CheckCircle2 } from 'lucide-react'
import type { Status } from '@/lib/mock-data'

interface StatusSelectorProps {
  initialStatus: Status
}

const statusLabels: Record<Status, string> = {
  PENDIENTE: 'Pendiente',
  EN_ATENCION: 'En Atención',
  CERRADO: 'Cerrado',
}

const statusColors: Record<Status, string> = {
  PENDIENTE: 'text-yellow-700 bg-yellow-50 border-yellow-200',
  EN_ATENCION: 'text-blue-700 bg-blue-50 border-blue-200',
  CERRADO: 'text-green-700 bg-green-50 border-green-200',
}

export function StatusSelector({ initialStatus }: StatusSelectorProps) {
  const [status, setStatus] = useState<Status>(initialStatus)
  const [saved, setSaved] = useState(false)

  const handleUpdate = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="text-sm font-medium text-gray-700">Estado del caso</label>
      <select
        value={status}
        onChange={(e) => { setStatus(e.target.value as Status); setSaved(false) }}
        className="w-full border border-gray-200 rounded-xl px-4 py-3 text-gray-900 bg-white focus:outline-none focus:ring-2 focus:ring-[#1168BD] focus:border-transparent cursor-pointer"
      >
        {(Object.keys(statusLabels) as Status[]).map((s) => (
          <option key={s} value={s}>{statusLabels[s]}</option>
        ))}
      </select>

      <div className={`px-4 py-2 rounded-xl border text-sm font-medium w-fit ${statusColors[status]}`}>
        {statusLabels[status]}
      </div>

      <Button variant="primary" size="md" onClick={handleUpdate} className="w-fit gap-2">
        {saved ? <CheckCircle2 className="w-4 h-4" /> : null}
        {saved ? 'Estado actualizado' : 'Actualizar estado'}
      </Button>
    </div>
  )
}
