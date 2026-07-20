"use client"

import { KioskProvider } from "@/components/providers/kiosk-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Building2 } from "lucide-react"
import Link from "next/link"

function KioskShell({ children }: { children: React.ReactNode }) {
  const { config } = useSystemConfig()
  return (
    <div className="flex min-h-screen flex-col bg-[#071426] text-white">
      <header className="flex min-h-16 items-center justify-between gap-4 border-b border-white/10 px-5 py-3 sm:px-8">
        <Link className="flex items-center gap-3" href="/">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#1168BD]">
            <Building2 className="h-5 w-5" />
          </span>
          <span>
            <span className="block text-sm font-semibold">{config?.bank_name ?? "Banco"}</span>
            <span className="block text-xs text-white/40">{config?.branch_name ?? ""}</span>
          </span>
        </Link>
        <span className="hidden text-xs text-white/35 sm:block">
          Atención segura · No ingreses PIN ni contraseñas
        </span>
      </header>
      <main className="flex flex-1 flex-col">{children}</main>
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
