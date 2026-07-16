import { Card } from '@/components/ui/card'
import type { ReactNode } from 'react'

interface KpiCardProps {
  title: string
  value: string | number
  subtitle?: string
  icon: ReactNode
  accentColor: string
}

export function KpiCard({ title, value, subtitle, icon, accentColor }: KpiCardProps) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs uppercase tracking-widest text-gray-400 font-medium">{title}</p>
          <p className="text-4xl font-bold text-gray-900 mt-2 leading-none">{value}</p>
          {subtitle && <p className="text-sm text-gray-500 mt-2">{subtitle}</p>}
        </div>
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: `${accentColor}18` }}
        >
          <div style={{ color: accentColor }}>{icon}</div>
        </div>
      </div>
    </Card>
  )
}
