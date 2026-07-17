"use client"

import { speak, useKiosk } from "@/components/providers/kiosk-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ApiError, errorMessage } from "@/lib/api"
import { priorityLabels } from "@/lib/labels"
import type { FlowResult } from "@/lib/types"
import { AlertTriangle, CheckCircle2, RotateCcw, ShieldCheck } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"

export default function ConfirmationPage() {
  const {
    session,
    analysis,
    hydrated,
    setResult,
    setTranscript,
    setAnalysis,
    setIsClarification,
    sessionRequest,
    reset,
  } = useKiosk()
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (hydrated && (!session || !analysis || analysis.next_action !== "CONFIRM")) {
      router.replace(session ? "/kiosco/voz" : "/kiosco")
    }
  }, [analysis, hydrated, router, session])

  async function confirm(confirmed: boolean) {
    setSubmitting(true)
    setError(null)
    try {
      const result = await sessionRequest<FlowResult>("/confirmation", {
        method: "POST",
        body: JSON.stringify({ confirmed }),
      })
      if (result.next_action !== "COMPLETE") {
        speak(result.speech_text)
      }
      if (!confirmed || result.next_action === "CAPTURE") {
        setTranscript("")
        setAnalysis(null)
        setIsClarification(false)
        router.replace("/kiosco/voz")
        return
      }
      setResult(result)
      if (result.next_action === "IDENTIFY") {
        router.push("/kiosco/identificacion")
      } else {
        router.push(result.resolution_type === "AUTOMATIC" ? "/kiosco/respuesta" : "/kiosco/ticket")
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
        reset()
        router.replace("/kiosco")
        return
      }
      setError(errorMessage(reason))
    } finally {
      setSubmitting(false)
    }
  }

  if (!analysis) return null

  return (
    <div className="flex flex-1 items-center justify-center px-5 py-10">
      <div className="w-full max-w-3xl space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-light sm:text-4xl">¿Esto es lo que nos indicó?</h1>
          <p className="mt-2 text-white/50">Confirme el resumen antes de continuar.</p>
        </div>

        <section className="space-y-5 rounded-3xl border border-white/15 bg-white/[.07] p-6 sm:p-8">
          <p className="text-xs uppercase tracking-widest text-white/40">Resumen protegido</p>
          <p className="text-2xl font-light leading-snug">{analysis.summary}</p>
          <div className="flex flex-wrap gap-3">
            <Badge variant={analysis.category} />
            <Badge variant={analysis.priority}>
              Prioridad: {priorityLabels[analysis.priority]}
            </Badge>
            <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-semibold uppercase text-white/70">
              Nivel: {analysis.consultation_level}
            </span>
          </div>
        </section>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex gap-3 rounded-2xl border border-yellow-400/25 bg-yellow-400/10 p-4">
            <AlertTriangle className="h-5 w-5 shrink-0 text-yellow-300" />
            <p className="text-sm text-yellow-100/80">
              Los datos detectados como sensibles fueron enmascarados antes del análisis.
            </p>
          </div>
          <div className="flex gap-3 rounded-2xl border border-green-400/25 bg-green-400/10 p-4">
            <ShieldCheck className="h-5 w-5 shrink-0 text-green-300" />
            <p className="text-sm text-green-100/80">
              La identificación, si se solicita, es demostrativa y no es autenticación bancaria.
            </p>
          </div>
        </div>

        {analysis.pii_types.length > 0 && (
          <p className="text-center text-xs text-white/35">
            Tipos protegidos: {analysis.pii_types.join(", ")}
          </p>
        )}
        {error && (
          <p className="rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200" role="alert">
            {error}
          </p>
        )}
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button
            className="flex-1"
            disabled={submitting}
            onClick={() => confirm(true)}
            size="xl"
          >
            <CheckCircle2 className="h-6 w-6" />
            {submitting ? "Procesando…" : "Sí, confirmar"}
          </Button>
          <Button
            className="flex-1"
            disabled={submitting}
            onClick={() => confirm(false)}
            size="xl"
            variant="ghost"
          >
            <RotateCcw className="h-6 w-6" />
            Corregir
          </Button>
        </div>
      </div>
    </div>
  )
}
