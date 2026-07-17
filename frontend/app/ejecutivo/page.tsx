"use client"

import { TicketCard } from "@/components/executive/ticket-card"
import { useAuth } from "@/components/providers/auth-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import type { TicketPage } from "@/lib/types"
import { RefreshCw } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

export default function ExecutivePage() {
  const { request } = useAuth()
  const { config } = useSystemConfig()
  const [page, setPage] = useState<TicketPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const response = await request<TicketPage>("/executive/tickets?page_size=100")
      setPage(response)
      setError(null)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [request])

  useEffect(() => {
    queueMicrotask(() => void load())
  }, [load])

  useEffect(() => {
    if (!config) return
    const timer = window.setInterval(() => void load(), config.dashboard_refresh_ms)
    return () => window.clearInterval(timer)
  }, [config, load])

  const tickets = page?.items ?? []
  const critical = tickets.filter(
    (ticket) => ticket.priority === "CRITICO" && ticket.status !== "CERRADO",
  ).length
  const inProgress = tickets.filter((ticket) => ticket.status === "EN_ATENCION").length

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Casos asignados</h1>
          <p className="mt-1 text-sm text-gray-500">
            {page?.total ?? 0} casos · {inProgress} en atención · {critical} críticos activos
          </p>
        </div>
        <Button disabled={loading} onClick={() => void load()} size="sm" variant="secondary">
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Actualizar
        </Button>
      </div>

      {error && (
        <p className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
      {loading && !page ? (
        <p className="rounded-2xl bg-white p-8 text-center text-gray-500">Cargando casos…</p>
      ) : tickets.length === 0 ? (
        <p className="rounded-2xl bg-white p-8 text-center text-gray-500">
          No existen casos asignados.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {tickets.map((ticket) => (
            <TicketCard key={ticket.id} ticket={ticket} />
          ))}
        </div>
      )}
    </div>
  )
}
