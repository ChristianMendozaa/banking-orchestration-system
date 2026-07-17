import { cn } from '@/lib/utils'
import type { Category, Priority } from '@/lib/types'

type BadgeVariant = Category | Priority | 'default'

interface BadgeProps {
  variant: BadgeVariant
  className?: string
  children?: React.ReactNode
}

const variantMap: Record<BadgeVariant, { bg: string; text: string; label: string }> = {
  CRITICO: { bg: 'bg-red-100', text: 'text-red-800', label: 'CRÍTICO' },
  ALTO: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'ALTO' },
  MEDIO: { bg: 'bg-yellow-100', text: 'text-yellow-800', label: 'MEDIO' },
  BAJO: { bg: 'bg-green-100', text: 'text-green-800', label: 'BAJO' },
  BLOQUEO_TARJETA: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'Bloqueo de Tarjeta' },
  REPORTE_FRAUDE: { bg: 'bg-red-100', text: 'text-red-800', label: 'Reporte de Fraude' },
  CONSULTA_GENERAL: { bg: 'bg-gray-100', text: 'text-gray-700', label: 'Consulta General' },
  SOLICITUD_CREDITO: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Solicitud de Crédito' },
  BANCA_DIGITAL: { bg: 'bg-purple-100', text: 'text-purple-800', label: 'Banca Digital' },
  default: { bg: 'bg-gray-100', text: 'text-gray-700', label: '' },
}

export function Badge({ variant, className, children }: BadgeProps) {
  const styles = variantMap[variant] ?? variantMap.default
  return (
    <span
      className={cn(
        'inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wide',
        styles.bg,
        styles.text,
        className,
      )}
    >
      {children ?? styles.label}
    </span>
  )
}
