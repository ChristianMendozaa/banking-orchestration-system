"use client"

import { useKiosk } from "@/components/providers/kiosk-provider"
import { Button } from "@/components/ui/button"
import { ApiError, errorMessage } from "@/lib/api"
import type { FlowResult } from "@/lib/types"
import { BadgeCheck, IdCard, ShieldAlert } from "lucide-react"
import { useRouter } from "next/navigation"
import { FormEvent, useEffect, useState } from "react"

export default function IdentificationPage() {
  const { session, result, hydrated, setResult, sessionRequest, reset } = useKiosk()
  const router = useRouter()
  const [identifier, setIdentifier] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (hydrated && (!session || result?.next_action !== "IDENTIFY")) {
      router.replace(session ? "/kiosco/voz" : "/kiosco")
    }
  }, [hydrated, result, router, session])

  async function identify(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const completed = await sessionRequest<FlowResult>("/identification", {
        method: "POST",
        body: JSON.stringify({ identifier: identifier.trim() }),
      })
      setResult(completed)
      router.replace(
        completed.resolution_type === "AUTOMATIC" ? "/kiosco/respuesta" : "/kiosco/ticket",
      )
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

  return (
    <div className="flex flex-1 items-center justify-center px-5 py-10">
      <div className="w-full max-w-xl rounded-3xl border border-white/15 bg-white/[.07] p-7 sm:p-9">
        <div className="text-center">
          <div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-[#1168BD]/30">
            <IdCard className="h-9 w-9 text-[#23A2D9]" />
          </div>
          <h1 className="mt-5 text-3xl font-semibold">Identificación demostrativa</h1>
          <p className="mt-3 text-white/55">
            Ingrese únicamente un identificador ficticio habilitado para esta demostración.
          </p>
        </div>

        <div className="my-6 flex gap-3 rounded-2xl border border-yellow-400/25 bg-yellow-400/10 p-4 text-sm text-yellow-100/80">
          <ShieldAlert className="h-5 w-5 shrink-0 text-yellow-300" />
          Esto no autentica una cuenta bancaria. Nunca ingrese CI real, contraseña, PIN, CVV ni
          número de cuenta.
        </div>

        <form className="space-y-4" onSubmit={identify}>
          <label className="block text-sm font-medium text-white/70">
            Identificador ficticio
            <input
              autoComplete="off"
              className="mt-2 w-full rounded-xl border border-white/15 bg-[#071426] px-4 py-4 text-lg uppercase outline-none focus:border-[#23A2D9]"
              maxLength={40}
              minLength={4}
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder="Identificador de demostración"
              required
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
            {submitting ? "Validando…" : "Validar y continuar"}
          </Button>
        </form>
      </div>
    </div>
  )
}
