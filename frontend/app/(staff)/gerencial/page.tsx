"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { CasesTable } from "@/components/gerencial/cases-table"
import { CategoryChart } from "@/components/gerencial/category-chart"
import { HourlyChart } from "@/components/gerencial/hourly-chart"
import { KpiCard } from "@/components/gerencial/kpi-card"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { errorMessage } from "@/lib/api"
import { categoryLabels, priorityLabels, statusLabels } from "@/lib/labels"
import type {
  Category,
  ManagementCasesPage,
  ManagementMetrics,
  Priority,
  TicketStatus,
} from "@/lib/types"
import { Activity, AlertTriangle, Clock, RefreshCw, Users } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"

export default function ManagerDashboardPage() {
  const { request } = useAuth()
  const { config } = useSystemConfig()
  const [metrics, setMetrics] = useState<ManagementMetrics | null>(null)
  const [cases, setCases] = useState<ManagementCasesPage | null>(null)
  const [category, setCategory] = useState<Category | "">("")
  const [priority, setPriority] = useState<Priority | "">("")
  const [status, setStatus] = useState<TicketStatus | "">("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const query = useMemo(() => {
    const params = new URLSearchParams({ page_size: "50" })
    if (category) params.set("category", category)
    if (priority) params.set("priority", priority)
    if (status) params.set("status", status)
    return params
  }, [category, priority, status])

  const load = useCallback(async () => {
    setLoading(true)
    const metricParams = new URLSearchParams(query)
    metricParams.delete("page_size")
    metricParams.delete("status")
    try {
      const [metricData, caseData] = await Promise.all([
        request<ManagementMetrics>(`/management/metrics?${metricParams}`),
        request<ManagementCasesPage>(`/management/cases?${query}`),
      ])
      setMetrics(metricData)
      setCases(caseData)
      setError(null)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [query, request])

  useEffect(() => {
    queueMicrotask(() => void load())
  }, [load])

  useEffect(() => {
    if (!config) return
    const timer = window.setInterval(() => void load(), config.dashboard_refresh_ms)
    return () => window.clearInterval(timer)
  }, [config, load])

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Resumen operativo del día</h1>
          <p className="mt-1 text-sm text-gray-500">
            Métricas de la sucursal, actualizadas desde el backend.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Filtrar categoría"
            className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm"
            onChange={(event) => setCategory(event.target.value as Category | "")}
            value={category}
          >
            <option value="">Todas las categorías</option>
            {(Object.entries(categoryLabels) as [Category, string][]).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            aria-label="Filtrar prioridad"
            className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm"
            onChange={(event) => setPriority(event.target.value as Priority | "")}
            value={priority}
          >
            <option value="">Todas las prioridades</option>
            {(Object.entries(priorityLabels) as [Priority, string][]).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            aria-label="Filtrar estado"
            className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm"
            onChange={(event) => setStatus(event.target.value as TicketStatus | "")}
            value={status}
          >
            <option value="">Todos los estados</option>
            {(Object.entries(statusLabels) as [TicketStatus, string][]).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <Button disabled={loading} onClick={() => void load()} size="sm" variant="secondary">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {error && (
        <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard title="Total casos" value={metrics?.total_cases ?? "—"} subtitle="Período actual" icon={<Users className="h-6 w-6" />} accentColor="#1168BD" />
        <KpiCard title="Activos" value={metrics?.active_cases ?? "—"} subtitle="Pendientes o en atención" icon={<Activity className="h-6 w-6" />} accentColor="#23A2D9" />
        <KpiCard title="Espera promedio" value={metrics ? `${metrics.average_wait_minutes} min` : "—"} subtitle="Hasta inicio de atención" icon={<Clock className="h-6 w-6" />} accentColor="#F59E0B" />
        <KpiCard title="Críticos activos" value={metrics?.critical_pending ?? "—"} subtitle="Requieren prioridad" icon={<AlertTriangle className="h-6 w-6" />} accentColor="#EF4444" />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Distribución por categoría</CardTitle></CardHeader>
          <CardContent><div className="h-[300px]"><CategoryChart data={metrics?.by_category ?? []} /></div></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Casos por hora</CardTitle></CardHeader>
          <CardContent><div className="h-[300px]"><HourlyChart data={metrics?.hourly ?? []} /></div></CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Casos del período ({cases?.total ?? 0})</CardTitle>
        </CardHeader>
        <CasesTable cases={cases?.items ?? []} />
      </Card>
    </div>
  )
}
