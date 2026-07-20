"use client"

import { CompletionStatus } from "@/components/kiosk/completion-status"
import { useKiosk } from "@/components/providers/kiosk-provider"
import { Badge } from "@/components/ui/badge"
import { Clock, MapPin, Shield, TicketCheck, User } from "lucide-react"

export default function TicketPage() {
  const { result, analysis, voiceError, completionSeconds } = useKiosk()

  if (!result?.ticket) return null
  const priority = result.priority ?? analysis?.priority
  const customerSummary = result.customer_summary ?? analysis?.customer_summary

  return (
    <div className="flex flex-1 items-center justify-center px-5 py-10">
      <div className="flex w-full max-w-3xl flex-col items-center gap-7">
        <div className="text-center">
          <div className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-[#1168BD]/25">
            <TicketCheck className="h-9 w-9 text-[#23A2D9]" />
          </div>
          <p className="text-sm uppercase tracking-widest text-white/45">
            Tu número de atención
          </p>
          <p className="mt-2 text-7xl font-bold tabular-nums sm:text-8xl">
            #{result.ticket.number}
          </p>
        </div>

        <div className="w-full rounded-2xl border border-[#23A2D9]/30 bg-[#1168BD]/15 px-6 py-4 text-center">
          <p className="text-lg font-medium text-[#7DD3FC]">
            Un ejecutivo continuará contigo.
          </p>
        </div>

        {result.executive ? (
          <section className="w-full rounded-3xl border border-white/15 bg-white/[.07] p-6">
            <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
              <div className="flex items-center gap-4">
                <div className="grid h-14 w-14 place-items-center rounded-full bg-[#1168BD]/30">
                  <User className="h-7 w-7 text-[#23A2D9]" />
                </div>
                <div>
                  <p className="text-xl font-semibold">{result.executive.name}</p>
                  <p className="mt-1 flex items-center gap-2 text-white/50">
                    <Shield className="h-4 w-4" />
                    {result.executive.title}
                  </p>
                </div>
              </div>
              {priority && <Badge variant={priority} />}
            </div>
            <div className="mt-5 flex flex-wrap gap-6 border-t border-white/10 pt-5">
              <p className="flex items-center gap-2 text-lg font-semibold text-[#23A2D9]">
                <MapPin className="h-5 w-5" />
                {result.executive.window_number}
              </p>
              <p className="flex items-center gap-2 text-white/45">
                <Clock className="h-5 w-5" />
                {result.ticket.estimated_wait_minutes !== null
                  ? `Espera estimada: ${result.ticket.estimated_wait_minutes} min`
                  : "Te llamaremos en breve"}
              </p>
            </div>
          </section>
        ) : (
          <p className="w-full rounded-2xl bg-white/[.06] p-5 text-center text-white/60">
            Estamos buscando al ejecutivo indicado. Conserva tu número de ticket.
          </p>
        )}

        {customerSummary && (
          <section className="w-full rounded-2xl border border-white/10 bg-white/[.04] p-5">
            <p className="text-xs uppercase tracking-widest text-white/35">Lo que necesitas</p>
            <p className="mt-2 text-white/80">{customerSummary}</p>
          </section>
        )}
        {result.identification_status === "FALLIDO" && (
          <p className="w-full rounded-xl border border-yellow-400/25 bg-yellow-400/10 p-4 text-sm text-yellow-100/80">
            No pudimos confirmar tu código. El ejecutivo te ayudará a completar la
            verificación de forma segura.
          </p>
        )}
        {result.tracking_information && (
          <p className="max-w-2xl text-center text-sm text-white/45">
            {result.tracking_information}
          </p>
        )}
        <CompletionStatus
          completionSeconds={completionSeconds}
          readingMessage="Estoy leyendo los datos de tu ticket."
          voiceError={voiceError}
        />
      </div>
    </div>
  )
}
