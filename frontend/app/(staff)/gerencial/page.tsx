"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { CasesTable } from "@/components/gerencial/cases-table"
import { CategoryChart } from "@/components/gerencial/category-chart"
import { HourlyChart } from "@/components/gerencial/hourly-chart"
import { KpiCard } from "@/components/gerencial/kpi-card"
import { PriorityChart } from "@/components/gerencial/priority-chart"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { errorMessage } from "@/lib/api"
import { categoryLabels, priorityLabels, statusLabels } from "@/lib/labels"
import type { Category, ManagementCasesPage, ManagementMetrics, Priority, TicketStatus } from "@/lib/types"
import { AlertTriangle, CheckCircle2, Clock3, Hourglass, RefreshCw, Search, UserRoundCheck } from "lucide-react"
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react"

function laPazDate(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/La_Paz",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date())
}

function shiftDate(value: string, days: number): string {
  const date = new Date(`${value}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export default function ManagerDashboardPage() {
  const { request } = useAuth()
  const { config } = useSystemConfig()
  const today = useMemo(() => laPazDate(), [])
  const [metrics, setMetrics] = useState<ManagementMetrics | null>(null)
  const [cases, setCases] = useState<ManagementCasesPage | null>(null)
  const [dateFrom, setDateFrom] = useState(today)
  const [dateTo, setDateTo] = useState(today)
  const [category, setCategory] = useState<Category | "">("")
  const [priority, setPriority] = useState<Priority | "">("")
  const [executiveId, setExecutiveId] = useState("")
  const [status, setStatus] = useState<TicketStatus | "">("")
  const [searchDraft, setSearchDraft] = useState("")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const sharedQuery = useMemo(() => {
    const params = new URLSearchParams({ date_from: `${dateFrom}T00:00:00`, date_to: `${shiftDate(dateTo, 1)}T00:00:00` })
    if (category) params.set("category", category)
    if (priority) params.set("priority", priority)
    if (executiveId) params.set("executive_id", executiveId)
    return params
  }, [category, dateFrom, dateTo, executiveId, priority])

  const casesQuery = useMemo(() => {
    const params = new URLSearchParams(sharedQuery)
    params.set("page", String(page))
    params.set("page_size", "20")
    if (status) params.set("status", status)
    if (search) params.set("q", search)
    return params
  }, [page, search, sharedQuery, status])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [metricData, caseData] = await Promise.all([
        request<ManagementMetrics>(`/management/metrics?${sharedQuery}`),
        request<ManagementCasesPage>(`/management/cases?${casesQuery}`),
      ])
      setMetrics(metricData)
      setCases(caseData)
      setError(null)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [casesQuery, request, sharedQuery])

  useEffect(() => { queueMicrotask(() => void load()) }, [load])
  useEffect(() => {
    if (!config) return
    const timer = window.setInterval(() => void load(), config.dashboard_refresh_ms)
    return () => window.clearInterval(timer)
  }, [config, load])

  function applyDays(days: number) {
    setDateFrom(shiftDate(today, -(days - 1))); setDateTo(today); setPage(1)
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault(); setSearch(searchDraft.trim()); setPage(1)
  }

  const totalPages = cases ? Math.max(1, Math.ceil(cases.total / cases.page_size)) : 1

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#1168BD]">Operación de sucursal</p><h1 className="mt-1 text-2xl font-bold text-gray-950">Panel gerencial</h1><p className="mt-1 text-sm text-gray-500">Carga, tiempos y resultados con acceso al expediente protegido.</p></div>
        <Button disabled={loading} onClick={() => void load()} size="sm" variant="secondary"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />Actualizar</Button>
      </div>

      <Card>
        <CardContent className="space-y-4 py-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => applyDays(1)} size="sm" variant={dateFrom === today && dateTo === today ? "primary" : "secondary"}>Hoy</Button>
            <Button onClick={() => applyDays(7)} size="sm" variant="secondary">7 días</Button>
            <Button onClick={() => applyDays(30)} size="sm" variant="secondary">30 días</Button>
            <label className="flex items-center gap-2 rounded-xl border border-gray-200 px-3 text-xs text-gray-500">Desde<input className="bg-white py-2 text-sm text-gray-800 outline-none" onChange={(event) => { setDateFrom(event.target.value); setPage(1) }} type="date" value={dateFrom} /></label>
            <label className="flex items-center gap-2 rounded-xl border border-gray-200 px-3 text-xs text-gray-500">Hasta<input className="bg-white py-2 text-sm text-gray-800 outline-none" onChange={(event) => { setDateTo(event.target.value); setPage(1) }} type="date" value={dateTo} /></label>
          </div>
          <div className="flex flex-wrap gap-2 border-t border-gray-100 pt-4">
            <select className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm" onChange={(event) => { setCategory(event.target.value as Category | ""); setPage(1) }} value={category}><option value="">Todas las categorías</option>{(Object.entries(categoryLabels) as [Category, string][]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
            <select className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm" onChange={(event) => { setPriority(event.target.value as Priority | ""); setPage(1) }} value={priority}><option value="">Toda prioridad</option>{(Object.entries(priorityLabels) as [Priority, string][]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
            <select className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm" onChange={(event) => { setExecutiveId(event.target.value); setPage(1) }} value={executiveId}><option value="">Todos los ejecutivos</option>{metrics?.executives.map((executive) => <option key={executive.id} value={executive.id}>{executive.name}</option>)}</select>
          </div>
        </CardContent>
      </Card>

      {error && <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">{error}</p>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <KpiCard title="Pendientes" value={metrics?.pending_cases ?? "—"} subtitle="Por atender" icon={<Hourglass className="h-6 w-6" />} accentColor="#F59E0B" />
        <KpiCard title="En atención" value={metrics?.in_attention_cases ?? "—"} subtitle="Ahora" icon={<UserRoundCheck className="h-6 w-6" />} accentColor="#1168BD" />
        <KpiCard title="Cerrados" value={metrics?.closed_cases ?? "—"} subtitle="En el período" icon={<CheckCircle2 className="h-6 w-6" />} accentColor="#10B981" />
        <KpiCard title="Críticos" value={metrics?.critical_pending ?? "—"} subtitle="Activos" icon={<AlertTriangle className="h-6 w-6" />} accentColor="#EF4444" />
        <KpiCard title="Espera prom." value={metrics ? `${metrics.average_wait_minutes} min` : "—"} subtitle="Hasta iniciar" icon={<Clock3 className="h-6 w-6" />} accentColor="#F59E0B" />
        <KpiCard title="Atención prom." value={metrics ? `${metrics.average_attention_minutes} min` : "—"} subtitle="Desde inicio" icon={<Clock3 className="h-6 w-6" />} accentColor="#8B5CF6" />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card><CardHeader><CardTitle>Por categoría</CardTitle></CardHeader><CardContent><div className="h-[280px]"><CategoryChart data={metrics?.by_category ?? []} /></div></CardContent></Card>
        <Card><CardHeader><CardTitle>Por prioridad</CardTitle></CardHeader><CardContent><div className="h-[280px]"><PriorityChart data={metrics?.by_priority ?? []} /></div></CardContent></Card>
        <Card><CardHeader><CardTitle>Casos por hora</CardTitle></CardHeader><CardContent><div className="h-[280px]"><HourlyChart data={metrics?.hourly ?? []} /></div></CardContent></Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Carga por ejecutivo</CardTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {metrics?.executives.map((executive) => <button className={`rounded-xl border p-4 text-left transition hover:border-[#1168BD]/30 ${executiveId === executive.id ? "border-[#1168BD] bg-blue-50" : "border-gray-100 bg-gray-50"}`} key={executive.id} onClick={() => { setExecutiveId(executiveId === executive.id ? "" : executive.id); setPage(1) }} type="button"><div className="flex items-start justify-between gap-2"><div><p className="font-semibold text-gray-900">{executive.name}</p><p className="mt-0.5 text-xs text-gray-500">{executive.title}</p></div><span className={`h-2.5 w-2.5 rounded-full ${executive.status === "DISPONIBLE" ? "bg-emerald-500" : executive.status === "OCUPADO" ? "bg-blue-500" : "bg-gray-400"}`} /></div><div className="mt-4 flex gap-4 text-xs text-gray-500"><span><b className="text-gray-900">{executive.pending}</b> pendientes</span><span><b className="text-gray-900">{executive.in_attention}</b> activo</span><span><b className="text-gray-900">{executive.closed}</b> cerrados</span></div></button>)}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"><div><CardTitle>Expedientes del período</CardTitle><p className="mt-1 text-sm text-gray-400">{cases?.total ?? 0} resultados</p></div><form className="flex flex-wrap gap-2" onSubmit={submitSearch}><label className="relative"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" /><input className="rounded-xl border border-gray-200 py-2 pl-9 pr-3 text-sm outline-none focus:border-[#1168BD]" onChange={(event) => setSearchDraft(event.target.value)} placeholder="Ticket o motivo" value={searchDraft} /></label><select className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm" onChange={(event) => { setStatus(event.target.value as TicketStatus | ""); setPage(1) }} value={status}><option value="">Todos los estados</option>{(Object.entries(statusLabels) as [TicketStatus, string][]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><Button size="sm" type="submit">Buscar</Button></form></CardHeader>
        <CasesTable cases={cases?.items ?? []} />
        {cases && totalPages > 1 && <div className="flex items-center justify-between border-t border-gray-100 p-4 text-sm text-gray-500"><span>Página {page} de {totalPages}</span><div className="flex gap-2"><Button disabled={page === 1} onClick={() => setPage((current) => current - 1)} size="sm" variant="secondary">Anterior</Button><Button disabled={page === totalPages} onClick={() => setPage((current) => current + 1)} size="sm" variant="secondary">Siguiente</Button></div></div>}
      </Card>
    </div>
  )
}
