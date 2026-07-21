import type { Category, Priority, ResolutionOutcome, TicketStatus } from "@/lib/types"

export const categoryLabels: Record<Category, string> = {
  BLOQUEO_TARJETA: "Bloqueo de tarjeta",
  REPORTE_FRAUDE: "Reporte de fraude",
  CONSULTA_GENERAL: "Consulta general",
  SOLICITUD_CREDITO: "Solicitud de crédito",
  BANCA_DIGITAL: "Banca digital",
}

export const categoryColors: Record<Category, string> = {
  BLOQUEO_TARJETA: "#F59E0B",
  REPORTE_FRAUDE: "#EF4444",
  CONSULTA_GENERAL: "#6B7280",
  SOLICITUD_CREDITO: "#1168BD",
  BANCA_DIGITAL: "#8B5CF6",
}

export const priorityLabels: Record<Priority, string> = {
  CRITICO: "Crítico",
  ALTO: "Alto",
  MEDIO: "Medio",
  BAJO: "Bajo",
}

export const statusLabels: Record<TicketStatus, string> = {
  PENDIENTE: "Pendiente",
  EN_ATENCION: "En atención",
  CERRADO: "Cerrado",
}

export const resolutionLabels: Record<ResolutionOutcome, string> = {
  RESUELTO: "Resuelto",
  DERIVADO: "Derivado",
  PENDIENTE_DOCUMENTACION: "Pendiente de documentación",
  CLIENTE_DESISTIO: "Cliente desistió",
  NO_RESUELTO: "No resuelto",
}

export function formatDateTime(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat("es-BO", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value))
}
