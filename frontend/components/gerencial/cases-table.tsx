"use client"

import Link from "next/link"
import { ArrowRight, Settings2, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { useAuth } from "@/components/providers/auth-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { formatDateTime, resolutionLabels, statusLabels } from "@/lib/labels"
import type {
  ExecutiveWorkload,
  ManagerialCase,
  Priority,
  TicketStatus,
} from "@/lib/types"

const statusDot: Record<TicketStatus, string> = {
  PENDIENTE: "bg-amber-400",
  EN_ATENCION: "bg-blue-500",
  CERRADO: "bg-emerald-500",
}

const priorities: Priority[] = ["BAJO", "MEDIO", "ALTO", "CRITICO"]

export function CasesTable({
  cases,
  executives,
  onChanged,
}: {
  cases: ManagerialCase[]
  executives: ExecutiveWorkload[]
  onChanged: () => Promise<void>
}) {
  const [selected, setSelected] = useState<ManagerialCase | null>(null)
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs uppercase tracking-widest text-gray-600">
            <th className="px-4 py-3 font-medium">Caso</th>
            <th className="px-4 py-3 font-medium">Prioridad</th>
            <th className="px-4 py-3 font-medium">Ejecutivo</th>
            <th className="px-4 py-3 font-medium">Estado</th>
            <th className="px-4 py-3 font-medium">Tiempos</th>
            <th className="px-4 py-3 font-medium">Resultado</th>
            <th className="px-4 py-3"><span className="sr-only">Abrir</span></th>
          </tr>
        </thead>
        <tbody>
          {cases.map((row) => (
            <tr className="border-b border-gray-50 transition hover:bg-blue-50/40" key={row.id}>
              <td className="max-w-xs px-4 py-3">
                <Link className="font-mono font-bold text-[#1168BD] hover:underline" href={`/gerencial/casos/${row.id}`}>{row.ticket}</Link>
                <p className="mt-1 line-clamp-1 text-xs text-gray-600">{row.summary}</p>
                <p className="mt-1 text-[11px] text-gray-500">{formatDateTime(row.created_at)}</p>
              </td>
              <td className="px-4 py-3"><div className="flex flex-col items-start gap-1"><Badge variant={row.priority} /><Badge variant={row.category} /></div></td>
              <td className="px-4 py-3 text-gray-700">{row.executive ?? "Sin asignar"}</td>
              <td className="px-4 py-3"><span className="flex items-center gap-2 text-gray-600"><span className={`h-2 w-2 rounded-full ${statusDot[row.status]}`} />{statusLabels[row.status]}</span></td>
              <td className="px-4 py-3 text-xs text-gray-500"><p>Espera: {row.wait_time_min} min</p><p className="mt-1">Atención: {row.attention_time_min === null ? "—" : `${row.attention_time_min} min`}</p></td>
              <td className="px-4 py-3 text-gray-600">{row.resolution_outcome ? resolutionLabels[row.resolution_outcome] : "—"}</td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-1">
                  {row.status === "PENDIENTE" && (
                    <button
                      aria-label={`Gestionar asignación y prioridad de ${row.ticket}`}
                      className="grid h-9 w-9 place-items-center rounded-lg text-gray-500 hover:bg-gray-100 hover:text-[#1168BD]"
                      onClick={() => setSelected(row)}
                      type="button"
                    >
                      <Settings2 className="h-4 w-4" />
                    </button>
                  )}
                  <Link aria-label={`Abrir ${row.ticket}`} className="grid h-9 w-9 place-items-center rounded-lg text-[#1168BD] hover:bg-[#1168BD]/10" href={`/gerencial/casos/${row.id}`}><ArrowRight className="h-4 w-4" /></Link>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {cases.length === 0 && <p className="p-10 text-center text-gray-500">No existen casos para los filtros seleccionados.</p>}
      </div>
      {selected && (
        <CaseOperationsDialog
          caseRecord={selected}
          executives={executives}
          onClose={() => setSelected(null)}
          onSaved={async () => {
            setSelected(null)
            await onChanged()
          }}
        />
      )}
    </>
  )
}

function CaseOperationsDialog({
  caseRecord,
  executives,
  onClose,
  onSaved,
}: {
  caseRecord: ManagerialCase
  executives: ExecutiveWorkload[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const { request } = useAuth()
  const [executiveId, setExecutiveId] = useState(caseRecord.executive_id ?? "")
  const [priority, setPriority] = useState<Priority>(caseRecord.priority)
  const [reason, setReason] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const higherPriorities = useMemo(
    () => priorities.slice(priorities.indexOf(caseRecord.priority)),
    [caseRecord.priority],
  )
  const changed =
    executiveId !== (caseRecord.executive_id ?? "") ||
    priority !== caseRecord.priority

  useEffect(() => {
    dialogRef.current?.focus()
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onClose()
    }
    window.addEventListener("keydown", closeOnEscape)
    return () => window.removeEventListener("keydown", closeOnEscape)
  }, [busy, onClose])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      let version = caseRecord.version
      if (executiveId !== (caseRecord.executive_id ?? "")) {
        const result = await request<{ version: number }>(
          `/management/tickets/${caseRecord.id}/assignment`,
          {
            method: "PATCH",
            body: JSON.stringify({
              executive_id: executiveId || null,
              expected_version: version,
              reason: reason.trim(),
            }),
          },
        )
        version = result.version
      }
      if (priority !== caseRecord.priority) {
        await request(`/management/tickets/${caseRecord.id}/priority`, {
          method: "PATCH",
          body: JSON.stringify({
            priority,
            expected_version: version,
            reason: reason.trim(),
          }),
        })
      }
      await onSaved()
    } catch (reasonValue) {
      setError(errorMessage(reasonValue))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      aria-labelledby="case-operation-title"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-slate-950/55 p-4"
      role="dialog"
    >
      <div
        className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl outline-none"
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-gray-950" id="case-operation-title">
              Gestionar {caseRecord.ticket}
            </h2>
            <p className="mt-1 text-sm text-gray-500">{caseRecord.summary}</p>
          </div>
          <button
            aria-label="Cerrar"
            className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"
            onClick={onClose}
            type="button"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="mt-6 space-y-4">
          <label className="block text-sm font-semibold text-gray-800">
            Ejecutivo
            <select
              className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 font-normal"
              onChange={(event) => setExecutiveId(event.target.value)}
              value={executiveId}
            >
              <option value="">Sin asignar</option>
              {executives
                .filter(
                  (executive) =>
                    executive.status === "DISPONIBLE" ||
                    executive.id === caseRecord.executive_id,
                )
                .map((executive) => (
                  <option key={executive.id} value={executive.id}>
                    {executive.name} · {executive.title}
                    {executive.status !== "DISPONIBLE" ? " · no disponible" : ""}
                  </option>
                ))}
            </select>
          </label>
          <label className="block text-sm font-semibold text-gray-800">
            Prioridad
            <select
              className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 font-normal"
              onChange={(event) => setPriority(event.target.value as Priority)}
              value={priority}
            >
              {higherPriorities.map((value) => (
                <option key={value} value={value}>
                  {value.replace("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm font-semibold text-gray-800">
            Motivo del cambio
            <textarea
              className="mt-2 min-h-24 w-full rounded-xl border border-gray-200 px-3 py-2.5 font-normal"
              maxLength={500}
              minLength={10}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Explica por qué se realiza el cambio."
              value={reason}
            />
          </label>
          {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">{error}</p>}
          <div className="flex justify-end gap-3">
            <Button disabled={busy} onClick={onClose} variant="secondary">Cancelar</Button>
            <Button
              disabled={busy || !changed || reason.trim().length < 10}
              onClick={() => void save()}
            >
              {busy ? "Guardando…" : "Guardar cambios"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
