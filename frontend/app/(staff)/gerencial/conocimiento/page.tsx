"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { errorMessage } from "@/lib/api"
import { categoryLabels, formatDateTime } from "@/lib/labels"
import type {
  Category,
  KnowledgeDocument,
  KnowledgeDocumentPage,
  KnowledgeJobResponse,
  KnowledgeSourceType,
} from "@/lib/types"
import {
  Archive,
  CheckCircle2,
  Download,
  FilePlus2,
  FileUp,
  Power,
  RefreshCw,
  Save,
  Search,
} from "lucide-react"
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react"

const allCategories = Object.keys(categoryLabels) as Category[]

function boliviaDate(value: string): string {
  return `${value}T12:00:00-04:00`
}

function inputDate(value: string | null): string {
  return value ? value.slice(0, 10) : ""
}

function fileSize(bytes: number): string {
  return new Intl.NumberFormat("es-BO", {
    style: "unit",
    unit: bytes >= 1_048_576 ? "megabyte" : "kilobyte",
    maximumFractionDigits: 1,
  }).format(bytes / (bytes >= 1_048_576 ? 1_048_576 : 1024))
}

function CategoryChecks({
  selected,
  onChange,
}: {
  selected: Category[]
  onChange: (categories: Category[]) => void
}) {
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium text-gray-700">Categorías habilitadas</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {allCategories.map((category) => (
          <label className="flex items-center gap-2 text-sm text-gray-600" key={category}>
            <input
              checked={selected.includes(category)}
              className="h-4 w-4 accent-[#1168BD]"
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...selected, category]
                    : selected.filter((item) => item !== category),
                )
              }
              type="checkbox"
            />
            {categoryLabels[category]}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function StatusPill({ document }: { document: KnowledgeDocument }) {
  const style =
    document.index_status === "READY"
      ? "bg-green-100 text-green-700"
      : document.index_status === "ARCHIVED"
        ? "bg-gray-100 text-gray-600"
        : document.index_status === "FAILED"
          ? "bg-red-100 text-red-700"
          : "bg-yellow-100 text-yellow-700"
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${style}`}>
      {document.index_status}
    </span>
  )
}

export default function KnowledgeManagementPage() {
  const { request, download } = useAuth()
  const [documents, setDocuments] = useState<KnowledgeDocumentPage | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [activeJob, setActiveJob] = useState<KnowledgeJobResponse | null>(null)
  const selected = useMemo(
    () => documents?.items.find((document) => document.id === selectedId) ?? null,
    [documents, selectedId],
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const query = new URLSearchParams({ page_size: "100" })
      if (search.trim()) query.set("search", search.trim())
      const response = await request<KnowledgeDocumentPage>(
        `/management/knowledge/documents?${query}`,
      )
      setDocuments(response)
      setError(null)
      setSelectedId((current) =>
        current && response.items.some((item) => item.id === current) ? current : null,
      )
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [request, search])

  useEffect(() => {
    queueMicrotask(() => void load())
  }, [load])

  useEffect(() => {
    if (!activeJob || !["QUEUED", "RUNNING"].includes(activeJob.job.status)) return
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        const current = await request<KnowledgeJobResponse>(
          `/management/knowledge/documents/jobs/${activeJob.job.id}`,
        )
        if (cancelled) return
        setActiveJob(current)
        if (current.job.status === "SUCCEEDED") {
          setNotice("La indexación terminó correctamente.")
          setActiveJob(null)
          await load()
        } else if (current.job.status === "FAILED") {
          setError(current.job.error_message ?? "No fue posible completar la indexación.")
          await load()
        }
      } catch (reason) {
        if (!cancelled) setError(errorMessage(reason))
      }
    }, 2_000)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [activeJob, load, request])

  function queueJob(result: KnowledgeJobResponse) {
    setSelectedId(result.document.id)
    setActiveJob(result)
    setNotice("Documento recibido. La indexación continuará en segundo plano.")
  }

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await action()
      await load()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function handleDownload(document: KnowledgeDocument) {
    await run(async () => {
      const result = await download(`/management/knowledge/documents/${document.id}/download`)
      const url = URL.createObjectURL(result.blob)
      const anchor = window.document.createElement("a")
      anchor.href = url
      anchor.download = result.fileName
      anchor.click()
      URL.revokeObjectURL(url)
      setNotice("Descarga preparada.")
    })
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Base de conocimiento</h1>
          <p className="mt-1 text-sm text-gray-500">
            Alta, actualización, versionado, archivo y reindexación de PDFs utilizados por el
            agente de atención inicial.
          </p>
        </div>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void load()
          }}
        >
          <label className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              aria-label="Buscar documentos"
              className="rounded-xl border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Buscar por título o slug"
              value={search}
            />
          </label>
          <Button disabled={loading} size="sm" type="submit" variant="secondary">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </form>
      </div>

      {error && (
        <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p
          className="flex items-center gap-2 rounded-xl border border-green-200 bg-green-50 p-4 text-sm text-green-700"
          role="status"
        >
          <CheckCircle2 className="h-4 w-4" />
          {notice}
        </p>
      )}
      {activeJob && (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800"
          role="status"
        >
          <span>
            Trabajo {activeJob.job.status === "FAILED" ? "fallido" : "en proceso"} · intento{" "}
            {activeJob.job.attempts}/{activeJob.job.max_attempts}
          </span>
          {activeJob.job.status === "FAILED" &&
            activeJob.job.attempts < activeJob.job.max_attempts && (
              <Button
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    const retried = await request<KnowledgeJobResponse>(
                      `/management/knowledge/documents/jobs/${activeJob.job.id}/retry`,
                      { method: "POST" },
                    )
                    setActiveJob(retried)
                    setNotice("Reintento encolado.")
                  })
                }
                size="sm"
                variant="secondary"
              >
                Reintentar
              </Button>
            )}
        </div>
      )}

      <CreateDocumentForm
        busy={busy}
        onCreate={(form) =>
          run(async () => {
            const result = await request<KnowledgeJobResponse>(
              "/management/knowledge/documents",
              { method: "POST", body: form },
            )
            queueJob(result)
          })
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(340px,.75fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Documentos ({documents?.total ?? 0})</CardTitle>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50 text-left text-xs uppercase tracking-wider text-gray-400">
                  <th className="px-4 py-3">Documento</th>
                  <th className="px-4 py-3">Versión</th>
                  <th className="px-4 py-3">Estado</th>
                  <th className="px-4 py-3">Índice</th>
                  <th className="px-4 py-3">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {documents?.items.map((document) => (
                  <tr
                    className={`cursor-pointer border-b border-gray-50 hover:bg-blue-50/50 ${
                      document.id === selectedId ? "bg-blue-50" : ""
                    }`}
                    key={document.id}
                    onClick={() => setSelectedId(document.id)}
                  >
                    <td className="px-4 py-3">
                      <p className="font-semibold text-gray-900">{document.title}</p>
                      <p className="text-xs text-gray-400">{document.slug}</p>
                    </td>
                    <td className="px-4 py-3 font-mono">{document.version}</td>
                    <td className="px-4 py-3"><StatusPill document={document} /></td>
                    <td className="px-4 py-3">{document.chunk_count} frag.</td>
                    <td className="px-4 py-3">
                      <button
                        className="rounded-lg p-2 text-[#1168BD] hover:bg-blue-100"
                        onClick={(event) => {
                          event.stopPropagation()
                          void handleDownload(document)
                        }}
                        title="Descargar PDF"
                        type="button"
                      >
                        <Download className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && documents?.items.length === 0 && (
              <p className="p-8 text-center text-gray-400">No se encontraron documentos.</p>
            )}
          </div>
        </Card>

        {selected ? (
          <DocumentEditor
            busy={busy}
            document={selected}
            key={`${selected.id}-${selected.updated_at}`}
            onToggleActive={() =>
              run(async () => {
                if (selected.active) {
                  if (!window.confirm("¿Desactivar y archivar esta versión documental?")) return
                  await request<void>(`/management/knowledge/documents/${selected.id}`, {
                    method: "DELETE",
                  })
                  setNotice("Versión desactivada y archivada.")
                  return
                }
                await request<KnowledgeDocument>(
                  `/management/knowledge/documents/${selected.id}`,
                  { method: "PATCH", body: JSON.stringify({ active: true }) },
                )
                setNotice("Versión activada; las demás versiones del mismo documento se desactivaron.")
              })
            }
            onReindex={() =>
              run(async () => {
                const result = await request<KnowledgeJobResponse>(
                  `/management/knowledge/documents/${selected.id}/reindex`,
                  { method: "POST" },
                )
                queueJob(result)
              })
            }
            onSave={(payload) =>
              run(async () => {
                await request<KnowledgeDocument>(
                  `/management/knowledge/documents/${selected.id}`,
                  { method: "PATCH", body: JSON.stringify(payload) },
                )
                setNotice("Metadatos actualizados.")
              })
            }
            onVersion={(form) =>
              run(async () => {
                const result = await request<KnowledgeJobResponse>(
                  `/management/knowledge/documents/${selected.id}/versions`,
                  { method: "POST", body: form },
                )
                queueJob(result)
              })
            }
          />
        ) : (
          <Card>
            <CardContent className="p-8 text-center text-sm text-gray-400">
              Seleccione un documento para administrar sus metadatos y versiones.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

function CreateDocumentForm({
  busy,
  onCreate,
}: {
  busy: boolean
  onCreate: (form: FormData) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [categories, setCategories] = useState<Category[]>(["CONSULTA_GENERAL"])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const raw = new FormData(event.currentTarget)
    const form = new FormData()
    const file = raw.get("file")
    if (!(file instanceof File) || !file.size) return
    form.set("file", file)
    form.set("slug", String(raw.get("slug") ?? "").trim())
    form.set("title", String(raw.get("title") ?? "").trim())
    form.set("version", String(raw.get("version") ?? "").trim())
    form.set("source_type", String(raw.get("source_type") ?? "INTERNAL"))
    form.set("categories", JSON.stringify(categories))
    form.set(
      "source_urls",
      JSON.stringify(
        String(raw.get("source_urls") ?? "")
          .split("\n")
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    )
    form.set("verified_at", boliviaDate(String(raw.get("verified_at"))))
    const review = String(raw.get("review_after") ?? "")
    if (review) form.set("review_after", boliviaDate(review))
    await onCreate(form)
    event.currentTarget.reset()
    setOpen(false)
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Incorporar documento</CardTitle>
          <p className="mt-1 text-sm text-gray-500">Solo PDF con texto extraíble; máximo definido por el backend.</p>
        </div>
        <Button onClick={() => setOpen((value) => !value)} size="sm">
          <FilePlus2 className="h-4 w-4" />
          {open ? "Cerrar" : "Nuevo"}
        </Button>
      </CardHeader>
      {open && (
        <CardContent>
          <form className="grid gap-4 md:grid-cols-2" onSubmit={submit}>
            <label className="text-sm text-gray-700">PDF<input accept="application/pdf" className="mt-1 block w-full rounded-xl border p-2" name="file" required type="file" /></label>
            <label className="text-sm text-gray-700">Slug<input className="mt-1 block w-full rounded-xl border p-2" name="slug" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="manual-atencion" required /></label>
            <label className="text-sm text-gray-700">Título<input className="mt-1 block w-full rounded-xl border p-2" minLength={3} name="title" required /></label>
            <label className="text-sm text-gray-700">Versión<input className="mt-1 block w-full rounded-xl border p-2" name="version" placeholder="2026.1" required /></label>
            <label className="text-sm text-gray-700">Tipo<select className="mt-1 block w-full rounded-xl border p-2" name="source_type"><option value="OFFICIAL">Oficial</option><option value="REGULATORY">Regulatorio</option><option value="INTERNAL">Interno</option><option value="HYBRID">Híbrido</option></select></label>
            <label className="text-sm text-gray-700">Fecha verificada<input className="mt-1 block w-full rounded-xl border p-2" name="verified_at" required type="date" /></label>
            <label className="text-sm text-gray-700">Revisar después de<input className="mt-1 block w-full rounded-xl border p-2" name="review_after" type="date" /></label>
            <label className="text-sm text-gray-700">URLs fuente, una por línea<textarea className="mt-1 block min-h-20 w-full rounded-xl border p-2" name="source_urls" /></label>
            <div className="md:col-span-2"><CategoryChecks onChange={setCategories} selected={categories} /></div>
            <Button className="md:col-span-2" disabled={busy || categories.length === 0} type="submit">
              <FileUp className="h-4 w-4" />{busy ? "Enviando…" : "Subir e indexar"}
            </Button>
          </form>
        </CardContent>
      )}
    </Card>
  )
}

function DocumentEditor({
  document,
  busy,
  onSave,
  onVersion,
  onToggleActive,
  onReindex,
}: {
  document: KnowledgeDocument
  busy: boolean
  onSave: (payload: Record<string, unknown>) => Promise<void>
  onVersion: (form: FormData) => Promise<void>
  onToggleActive: () => Promise<void>
  onReindex: () => Promise<void>
}) {
  const [title, setTitle] = useState(document.title)
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>(document.source_type)
  const [categories, setCategories] = useState<Category[]>(document.categories)
  const [sourceUrls, setSourceUrls] = useState(document.source_urls.join("\n"))
  const [verifiedAt, setVerifiedAt] = useState(inputDate(document.verified_at))
  const [reviewAfter, setReviewAfter] = useState(inputDate(document.review_after))

  async function save(event: FormEvent) {
    event.preventDefault()
    await onSave({
      title: title.trim(),
      source_type: sourceType,
      categories,
      source_urls: sourceUrls.split("\n").map((item) => item.trim()).filter(Boolean),
      verified_at: boliviaDate(verifiedAt),
      review_after: reviewAfter ? boliviaDate(reviewAfter) : null,
    })
  }

  async function version(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const raw = new FormData(event.currentTarget)
    const form = new FormData()
    const file = raw.get("file")
    if (!(file instanceof File) || !file.size) return
    form.set("file", file)
    form.set("version", String(raw.get("version") ?? "").trim())
    form.set("verified_at", boliviaDate(String(raw.get("verified_at"))))
    const review = String(raw.get("review_after") ?? "")
    if (review) form.set("review_after", boliviaDate(review))
    await onVersion(form)
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Versión {document.version}</CardTitle>
            <StatusPill document={document} />
          </div>
          <p className="mt-1 text-xs text-gray-400">
            {document.page_count} pág. · {fileSize(document.byte_size)} · {document.chunk_count} fragmentos
          </p>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={save}>
            <label className="block text-sm text-gray-700">Título<input className="mt-1 w-full rounded-xl border p-2" minLength={3} onChange={(event) => setTitle(event.target.value)} required value={title} /></label>
            <label className="block text-sm text-gray-700">Tipo<select className="mt-1 w-full rounded-xl border p-2" onChange={(event) => setSourceType(event.target.value as KnowledgeSourceType)} value={sourceType}><option value="OFFICIAL">Oficial</option><option value="REGULATORY">Regulatorio</option><option value="INTERNAL">Interno</option><option value="HYBRID">Híbrido</option></select></label>
            <CategoryChecks onChange={setCategories} selected={categories} />
            <label className="block text-sm text-gray-700">URLs fuente<textarea className="mt-1 min-h-20 w-full rounded-xl border p-2" onChange={(event) => setSourceUrls(event.target.value)} value={sourceUrls} /></label>
            <div className="grid grid-cols-2 gap-3">
              <label className="text-sm text-gray-700">Verificado<input className="mt-1 w-full rounded-xl border p-2" onChange={(event) => setVerifiedAt(event.target.value)} required type="date" value={verifiedAt} /></label>
              <label className="text-sm text-gray-700">Revisión<input className="mt-1 w-full rounded-xl border p-2" onChange={(event) => setReviewAfter(event.target.value)} type="date" value={reviewAfter} /></label>
            </div>
            <Button className="w-full" disabled={busy || categories.length === 0} type="submit"><Save className="h-4 w-4" />Guardar metadatos</Button>
          </form>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Button disabled={busy} onClick={onReindex} size="sm" variant="secondary"><RefreshCw className="h-4 w-4" />Reindexar</Button>
            <Button
              disabled={busy}
              onClick={onToggleActive}
              size="sm"
              variant={document.active ? "danger" : "secondary"}
            >
              {document.active ? <Archive className="h-4 w-4" /> : <Power className="h-4 w-4" />}
              {document.active ? "Desactivar" : "Activar"}
            </Button>
          </div>
          <p className="mt-4 text-xs text-gray-400">
            Indexado: {formatDateTime(document.indexed_at)} · SHA-256: {document.content_sha256.slice(0, 12)}…
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Nueva versión</CardTitle></CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={version}>
            <input accept="application/pdf" className="w-full rounded-xl border p-2 text-sm" name="file" required type="file" />
            <input className="w-full rounded-xl border p-2 text-sm" name="version" placeholder="Nueva versión" required />
            <div className="grid grid-cols-2 gap-2">
              <input aria-label="Fecha verificada" className="rounded-xl border p-2 text-sm" name="verified_at" required type="date" />
              <input aria-label="Fecha de revisión" className="rounded-xl border p-2 text-sm" name="review_after" type="date" />
            </div>
            <Button className="w-full" disabled={busy} size="sm" type="submit"><FilePlus2 className="h-4 w-4" />Crear e indexar versión</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
