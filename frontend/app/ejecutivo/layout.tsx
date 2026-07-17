"use client"

import { RoleGuard, useAuth } from "@/components/providers/auth-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Building2, LogOut } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"

function ExecutiveShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const { config } = useSystemConfig()
  const router = useRouter()

  async function exit() {
    await logout()
    router.replace("/login")
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#F3F4F6]">
      <header className="flex min-h-16 items-center justify-between gap-4 border-b border-gray-200 bg-white px-5 py-3 sm:px-6">
        <Link className="flex items-center gap-3" href="/ejecutivo">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#0A1628]">
            <Building2 className="h-5 w-5 text-white" />
          </span>
          <span>
            <span className="block text-sm font-bold text-gray-900">
              {config?.bank_name ?? "Sistema bancario"}
            </span>
            <span className="block text-xs text-gray-400">{config?.branch_name}</span>
          </span>
        </Link>
        <div className="flex items-center gap-3">
          <div className="hidden text-right sm:block">
            <p className="text-sm font-semibold text-gray-900">{user?.email}</p>
            <p className="text-xs text-gray-400">Ejecutivo de atención</p>
          </div>
          <button
            aria-label="Cerrar sesión"
            className="rounded-xl p-2 text-gray-500 transition hover:bg-red-50 hover:text-red-600"
            onClick={exit}
            type="button"
          >
            <LogOut className="h-5 w-5" />
          </button>
        </div>
      </header>
      <div className="flex flex-1">
        <aside className="hidden w-60 border-r border-gray-200 bg-white p-4 md:block">
          <nav>
            <Link
              className="block rounded-xl border-l-4 border-[#1168BD] bg-[#1168BD]/10 px-4 py-3 text-sm font-semibold text-[#1168BD]"
              href="/ejecutivo"
            >
              Casos asignados
            </Link>
          </nav>
        </aside>
        <main className="min-w-0 flex-1 p-4 sm:p-6">{children}</main>
      </div>
    </div>
  )
}

export default function ExecutiveLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["EXECUTIVE"]}>
      <ExecutiveShell>{children}</ExecutiveShell>
    </RoleGuard>
  )
}
