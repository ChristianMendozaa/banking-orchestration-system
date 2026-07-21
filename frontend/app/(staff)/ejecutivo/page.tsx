"use client"

import { TicketCard } from "@/components/executive/ticket-card"
import { useAuth } from "@/components/providers/auth-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { categoryLabels, priorityLabels, statusLabels } from "@/lib/labels"
import type { Category, Priority, TicketPage, TicketStatus } from "@/lib/types"
import { RefreshCw, Search, SlidersHorizontal } from "lucide-react"
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react"

const tabs: TicketStatus[] = ["PENDIENTE", "EN_ATENCION", "CERRADO"]

export default function ExecutivePage() {
  const { request } = useAuth()
  const { config } = useSystemConfig()
  const [data, setData] = useState<TicketPage | null>(null)
  const [status, setStatus] = useState<TicketStatus | null>(null)
  const [category, setCategory] = useState<Category | "">("")
  const [priority, setPriority] = useState<Priority | "">("")
  const [sort, setSort] = useState<"priority" | "oldest" | "newest">("priority")
  const [searchDraft, setSearchDraft] = useState("")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: "12", sort })
    if (status) params.set("status", status)
    if (category) params.set("category", category)
    if (priority) params.set("priority", priority)
    if (search) params.set("q", search)
    return params
  }, [category, page, priority, search, sort, status])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await request<TicketPage>(`/executive/tickets?${query}`)
      setData(response)
      setUpdatedAt(new Date())
      setError(null)
      if (!status) {
        setStatus(response.status_counts.EN_ATENCION > 0 ? "EN_ATENCION" : "PENDIENTE")
      }
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [query, request, status])

  useEffect(() => {
    queueMicrotask(() => void load())
  }, [load])

  useEffect(() => {
    if (!config) return
    const timer = window.setInterval(() => void load(), config.dashboard_refresh_ms)
    return () => window.clearInterval(timer)
  }, [config, load])

  function submitSearch(event: FormEvent) {
    event.preventDefault()
    setPage(1)
    setSearch(searchDraft.trim())
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <div className="mx-auto max-w-6xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#1168BD]">Mi jornada</p>
          <h1 className="mt-1 text-2xl font-bold text-gray-950">Casos asignados</h1>
          <p className="mt-1 text-sm text-gray-500">
            Prioriza tu caso actual y distingue rápidamente lo que falta atender.
          </p>
        </div>
        <div className="text-right">
          <Button disabled={loading} onClick={() => void load()} size="sm" variant="secondary">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Actualizar
          </Button>
          {updatedAt && (
            <p className="mt-1 text-xs text-gray-400">
              Actualizado {updatedAt.toLocaleTimeString("es-BO", { hour: "2-digit", minute: "2-digit" })}
            </p>
          )}
        </div>
      </div>

      <div className="mb-5 grid grid-cols-3 gap-2 rounded-2xl bg-white p-2 shadow-sm ring-1 ring-gray-100">
        {tabs.map((tab) => {
          const active = status === tab
          return (
            <button
              className={`rounded-xl px-3 py-3 text-sm font-semibold transition ${
                active ? "bg-[#0A1628] text-white shadow-sm" : "text-gray-500 hover:bg-gray-50"
              }`}
              key={tab}
              onClick={() => { setStatus(tab); setPage(1) }}
              type="button"
            >
              <span className="block sm:inline">{statusLabels[tab]}</span>
              <span className={`ml-0 mt-1 inline-flex min-w-6 justify-center rounded-full px-1.5 py-0.5 text-xs sm:ml-2 sm:mt-0 ${
                active ? "bg-white/15 text-white" : "bg-gray-100 text-gray-600"
              }`}>
                {data?.status_counts[tab] ?? 0}
              </span>
            </button>
          )
        })}
      </div>

      <div className="mb-5 rounded-2xl border border-gray-100 bg-white p-4 shadow-sm">
        <form className="flex flex-col gap-3 lg:flex-row" onSubmit={submitSearch}>
          <label className="relative min-w-0 flex-1">
            <span className="sr-only">Buscar casos</span>
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              className="w-full rounded-xl border border-gray-200 py-2.5 pl-10 pr-3 text-sm outline-none focus:border-[#1168BD] focus:ring-2 focus:ring-[#1168BD]/15"
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="Ticket, cliente, CI o motivo"
              value={searchDraft}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <select className="min-w-40 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm" onChange={(event) => { setCategory(event.target.value as Category | ""); setPage(1) }} value={category}>
              <option value="">Todas las categorías</option>
              {(Object.entries(categoryLabels) as [Category, string][]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <select className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm" onChange={(event) => { setPriority(event.target.value as Priority | ""); setPage(1) }} value={priority}>
              <option value="">Toda prioridad</option>
              {(Object.entries(priorityLabels) as [Priority, string][]).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <label className="flex items-center gap-2 rounded-xl border border-gray-200 px-3">
              <SlidersHorizontal className="h-4 w-4 text-gray-400" />
              <select className="bg-white py-2 text-sm outline-none" onChange={(event) => { setSort(event.target.value as typeof sort); setPage(1) }} value={sort}>
                <option value="priority">Prioridad</option>
                <option value="oldest">Más antiguos</option>
                <option value="newest">Más recientes</option>
              </select>
            </label>
            <Button size="sm" type="submit">Buscar</Button>
          </div>
        </form>
      </div>

      {error && <p className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">{error}</p>}

      {loading && !data ? (
        <div className="space-y-3" aria-label="Cargando casos">
          {[1, 2, 3].map((item) => <div className="h-36 animate-pulse rounded-2xl bg-white" key={item} />)}
        </div>
      ) : !status ? null : (data?.items.length ?? 0) === 0 ? (
        <div className="rounded-2xl border border-dashed border-gray-200 bg-white p-10 text-center">
          <p className="font-semibold text-gray-700">No hay casos {statusLabels[status].toLowerCase()}.</p>
          <p className="mt-1 text-sm text-gray-400">Prueba limpiando los filtros o seleccionando otro estado.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {data?.items.map((ticket) => <TicketCard key={ticket.id} ticket={ticket} />)}
        </div>
      )}

      {data && totalPages > 1 && (
        <div className="mt-6 flex items-center justify-between text-sm text-gray-500">
          <span>Página {page} de {totalPages}</span>
          <div className="flex gap-2">
            <Button disabled={page === 1} onClick={() => setPage((current) => current - 1)} size="sm" variant="secondary">Anterior</Button>
            <Button disabled={page === totalPages} onClick={() => setPage((current) => current + 1)} size="sm" variant="secondary">Siguiente</Button>
          </div>
        </div>
      )}
    </div>
  )
}
