"use client"

import { KioskProvider } from "@/components/providers/kiosk-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Building2, RefreshCw } from "lucide-react"
import Link from "next/link"

function KioskShell({ children }: { children: React.ReactNode }) {
  const { config, error, loading, reload } = useSystemConfig()
  return (
    <div className="flex min-h-screen flex-col bg-[#071426] text-white">
      <header className="flex min-h-16 items-center justify-between gap-4 border-b border-white/10 px-5 py-3 sm:px-8">
        <Link className="flex items-center gap-3" href="/">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#1168BD]">
            <Building2 className="h-5 w-5" />
          </span>
          <span>
            <span className="block text-sm font-semibold">{config?.bank_name ?? "Banco"}</span>
            <span className="block text-xs text-white/70">{config?.branch_name ?? ""}</span>
          </span>
        </Link>
        <span className="hidden text-xs text-white/65 sm:block">
          Atención segura · No ingreses PIN ni contraseñas
        </span>
      </header>
      {error && (
        <div
          className="flex items-center justify-center gap-3 border-b border-amber-300/25 bg-amber-300/10 px-5 py-3 text-sm text-amber-100"
          role="alert"
        >
          <span>No pudimos cargar la información de la sucursal.</span>
          <button
            className="inline-flex items-center gap-1 font-semibold underline underline-offset-4"
            disabled={loading}
            onClick={() => void reload()}
            type="button"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Reintentar
          </button>
        </div>
      )}
      <main className="flex flex-1 flex-col" id="main-content">{children}</main>
    </div>
  )
}

export default function KioskLayout({ children }: { children: React.ReactNode }) {
  return (
    <KioskProvider>
      <KioskShell>{children}</KioskShell>
    </KioskProvider>
  )
}
