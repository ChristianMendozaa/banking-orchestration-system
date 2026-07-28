"use client"

import { useKiosk } from "@/components/providers/kiosk-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import {
  BadgeCheck,
  CircleAlert,
  IdCard,
  RefreshCw,
  ShieldAlert,
} from "lucide-react"
import { FormEvent, useEffect, useState } from "react"

export default function IdentificationPage() {
  const {
    session,
    result,
    hydrated,
    voiceState,
    voiceError,
    connectVoice,
    retryVoice,
    reset,
    submitIdentification,
    interactionMode,
  } = useKiosk()
  const [identifier, setIdentifier] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (
      interactionMode === "voice" &&
      hydrated &&
      session &&
      result?.next_action === "IDENTIFY" &&
      voiceState === "idle"
    ) {
      void connectVoice().catch(() => {
        // La identificación escrita puede continuar aunque falle la voz.
      })
    }
  }, [connectVoice, hydrated, interactionMode, result, session, voiceState])

  async function identify(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await submitIdentification(identifier)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setSubmitting(false)
    }
  }

  function returnToStart() {
    reset()
  }

  if (!hydrated || !session || result?.next_action !== "IDENTIFY") return null

  return (
    <div className="flex flex-1 items-center justify-center px-5 py-10">
      <div className="w-full max-w-xl rounded-3xl border border-white/15 bg-white/[.07] p-7 sm:p-9">
        <div className="text-center">
          <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-[#1168BD]/30">
            <IdCard className="h-9 w-9 text-[#23A2D9]" />
          </div>
          <h1 className="mt-5 text-3xl font-semibold">Confirma tu identidad</h1>
          <p className="mt-3 text-white/75">
            Ingresa tu CI en este campo protegido para asociarlo con la solicitud.
          </p>
        </div>

        <div
          className="my-6 flex gap-3 rounded-2xl border border-yellow-400/25 bg-yellow-400/10 p-4 text-sm text-yellow-100/80"
          id="identifier-security-note"
        >
          <ShieldAlert className="h-5 w-5 shrink-0 text-yellow-300" />
          Este paso no autoriza operaciones bancarias. Nunca ingreses contraseña, PIN, CVV ni
          números completos de tarjeta o cuenta.
        </div>

        {voiceError && (
          <div className="mb-6 rounded-2xl border border-red-400/30 bg-red-400/10 p-4">
            <p className="flex items-start gap-2 text-sm text-red-100" role="alert">
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
              {voiceError}
            </p>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <Button onClick={() => void retryVoice()} type="button">
                <RefreshCw className="h-4 w-4" />
                Reintentar voz
              </Button>
              <Button onClick={returnToStart} type="button" variant="ghost">
                Volver al inicio y pedir ayuda
              </Button>
            </div>
          </div>
        )}

        <form aria-busy={submitting} className="space-y-4" onSubmit={identify}>
          <label className="block text-sm font-medium text-white/70">
            CI del cliente
            <input
              aria-describedby="identifier-security-note identifier-next-step"
              autoCapitalize="characters"
              autoComplete="off"
              className="mt-2 w-full rounded-xl border border-white/15 bg-[#071426] px-4 py-4 text-lg uppercase outline-none focus:border-[#23A2D9]"
              disabled={submitting}
              maxLength={16}
              minLength={4}
              onChange={(event) => setIdentifier(event.target.value.toUpperCase())}
              pattern="[0-9]{4,12}(-[A-Za-z]{1,3})?"
              placeholder="Ej.: 6735666 o 6735666-SC"
              required
              title="Ingresa entre 4 y 12 dígitos y, opcionalmente, una extensión como -SC"
              value={identifier}
            />
          </label>
          {error && (
            <p className="rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200" role="alert">
              {error}
            </p>
          )}
          <Button className="w-full" disabled={submitting} size="lg" type="submit">
            <BadgeCheck className="h-5 w-5" />
            {submitting ? "Estoy validando tu CI…" : "Validar mi CI y continuar"}
          </Button>
          <p className="text-center text-sm text-white/70" id="identifier-next-step">
            Después de validar el CI, verás tu número de ticket y los datos para
            continuar.
          </p>
        </form>
      </div>
    </div>
  )
}
