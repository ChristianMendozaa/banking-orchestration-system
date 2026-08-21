"use client"

import { AutomaticAnswer } from "@/components/kiosk/automatic-answer"
import { useKiosk } from "@/components/providers/kiosk-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { Check, Keyboard, Mic, RotateCcw, Send } from "lucide-react"
import { FormEvent, useState } from "react"

export function TextInteraction() {
  const {
    analysis,
    result,
    submitTextTurn,
    confirmText,
    interruptSpeech,
    selectInteractionMode,
  } = useKiosk()
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    const text = message.trim()
    if (text.length < 2) return
    interruptSpeech()
    setBusy(true)
    setError(null)
    try {
      await submitTextTurn(text)
      setMessage("")
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  async function confirm(confirmed: boolean) {
    setBusy(true)
    setError(null)
    try {
      await confirmText(confirmed)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  const confirmation = analysis?.next_action === "CONFIRM"
  const answered =
    result?.next_action === "COMPLETE" && result.resolution_type === "AUTOMATIC"
  const assistantMessage =
    analysis?.speech_text ??
    (answered ? "¿Te ayudo con algo más?" : result?.speech_text) ??
    "Hola, soy tu asistente virtual. Escribe brevemente qué necesitas resolver."

  return (
    <div className="flex flex-1 flex-col items-center gap-7 px-5 py-8 sm:px-8">
      <div className="w-full max-w-3xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-widest text-[#38BDF8]">
              <Keyboard className="h-4 w-4" />
              Atención por texto
            </p>
            <h1 className="mt-3 text-3xl font-light sm:text-4xl">
              Cuéntame cómo puedo ayudarte
            </h1>
          </div>
          <Button
            onClick={() => selectInteractionMode("voice")}
            size="sm"
            variant="ghost"
          >
            <Mic className="h-4 w-4" />
            Prefiero hablar
          </Button>
        </div>

        <section
          aria-live="polite"
          className="mt-8 rounded-3xl rounded-tl-none border border-white/15 bg-white/[.08] px-6 py-5"
        >
          <p className="text-xs font-semibold uppercase tracking-widest text-[#38BDF8]">
            Asistente
          </p>
          <p className="mt-3 text-lg leading-relaxed text-white/90">
            {assistantMessage}
          </p>
          {analysis?.customer_summary && (
            <p className="mt-4 rounded-xl bg-black/20 p-4 text-sm text-white/75">
              {analysis.customer_summary}
            </p>
          )}
        </section>

        {answered && result && (
          <div className="mt-6">
            <AutomaticAnswer result={result} />
          </div>
        )}

        {confirmation ? (
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <Button
              disabled={busy}
              onClick={() => void confirm(true)}
              size="lg"
            >
              <Check className="h-5 w-5" />
              Sí, es correcto
            </Button>
            <Button
              disabled={busy}
              onClick={() => void confirm(false)}
              size="lg"
              variant="ghost"
            >
              <RotateCcw className="h-5 w-5" />
              No, quiero corregir
            </Button>
          </div>
        ) : (
          <form className="mt-6 space-y-3" onSubmit={submit}>
            <label className="block text-sm font-semibold text-white/80" htmlFor="text-request">
              Tu mensaje
            </label>
            <textarea
              autoFocus
              className="min-h-32 w-full resize-y rounded-2xl border border-white/20 bg-white/[.08] px-5 py-4 text-lg text-white outline-none placeholder:text-white/65 focus:border-[#38BDF8] focus:ring-2 focus:ring-[#38BDF8]/30"
              disabled={busy}
              id="text-request"
              maxLength={4000}
              minLength={2}
              onChange={(event) => {
                if (!message && event.target.value) interruptSpeech()
                setMessage(event.target.value)
              }}
              placeholder="Escribe aquí sin incluir contraseñas, PIN, CVV ni números financieros completos."
              required
              value={message}
            />
            <div className="flex items-center justify-between gap-4">
              <span className="text-xs text-white/70">{message.length}/4000</span>
              <Button disabled={busy || message.trim().length < 2} size="lg" type="submit">
                <Send className="h-5 w-5" />
                {busy ? "Procesando…" : "Enviar"}
              </Button>
            </div>
          </form>
        )}

        {error && (
          <p className="mt-5 rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-100" role="alert">
            {error}
          </p>
        )}

        <p className="mt-8 text-center text-sm text-white/60">
          No escribas contraseñas, PIN, CVV ni números completos de tarjeta o cuenta.
        </p>
      </div>
    </div>
  )
}
