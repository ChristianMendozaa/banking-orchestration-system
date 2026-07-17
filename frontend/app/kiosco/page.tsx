"use client"

import { Clock } from "@/components/kiosk/clock"
import { useKiosk } from "@/components/providers/kiosk-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { Accessibility, ArrowRight, Building2, ShieldCheck } from "lucide-react"
import { useRouter } from "next/navigation"
import { useState } from "react"

export default function KioskPage() {
  const { config } = useSystemConfig()
  const { beginSession, reset } = useKiosk()
  const router = useRouter()
  const [preferential, setPreferential] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function start() {
    setStarting(true)
    setError(null)
    reset()
    try {
      await beginSession(preferential)
      router.push("/kiosco/voz")
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-between gap-10 px-6 py-10 sm:py-12">
      <div className="flex flex-col items-center gap-4 text-center">
        <div className="grid h-20 w-20 place-items-center rounded-3xl border border-[#23A2D9]/30 bg-[#1168BD]/20">
          <Building2 className="h-10 w-10 text-[#23A2D9]" />
        </div>
        <div>
          <p className="text-xl font-bold">{config?.bank_name ?? "Cargando…"}</p>
          <p className="mt-1 text-sm text-white/45">{config?.branch_name}</p>
        </div>
      </div>

      <div className="w-full max-w-3xl text-center">
        <h1 className="text-4xl font-light leading-tight sm:text-6xl">
          Bienvenido al sistema de
          <span className="mt-2 block font-bold text-[#23A2D9]">atención inteligente</span>
        </h1>
        <p className="mt-5 text-lg text-white/60">
          Describa su necesidad con su voz o mediante el teclado.
        </p>

        <label className="mx-auto mt-8 flex max-w-xl cursor-pointer items-start gap-4 rounded-2xl border border-white/15 bg-white/[.06] p-4 text-left">
          <input
            checked={preferential}
            className="mt-1 h-5 w-5 accent-[#1168BD]"
            onChange={(event) => setPreferential(event.target.checked)}
            type="checkbox"
          />
          <span>
            <span className="flex items-center gap-2 font-semibold">
              <Accessibility className="h-5 w-5 text-[#23A2D9]" />
              Solicito atención preferente
            </span>
            <span className="mt-1 block text-sm text-white/50">
              Marque esta opción si corresponde según las condiciones de atención del prototipo.
            </span>
          </span>
        </label>

        {error && (
          <p className="mx-auto mt-5 max-w-xl rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">
            {error}
          </p>
        )}
        <Button
          className="mt-8 gap-3 shadow-2xl shadow-[#1168BD]/30"
          disabled={starting}
          onClick={start}
          size="xl"
        >
          {starting ? "Creando sesión…" : "Iniciar atención"}
          {!starting && <ArrowRight className="h-7 w-7" />}
        </Button>
        <p className="mt-5 flex items-center justify-center gap-2 text-sm text-white/40">
          <ShieldCheck className="h-4 w-4" />
          La transcripción original y el audio no se almacenan.
        </p>
      </div>

      <Clock />
    </div>
  )
}
