"use client"

import { RoleGuard, useAuth } from "@/components/providers/auth-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { BookOpen, Building2, LayoutDashboard, LogOut } from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"

function ManagerShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const { config } = useSystemConfig()
  const path = usePathname()
  const router = useRouter()
  const nav = [
    { href: "/gerencial", label: "Dashboard", icon: LayoutDashboard },
    { href: "/gerencial/conocimiento", label: "Conocimiento", icon: BookOpen },
  ]

  async function exit() {
    await logout()
    router.replace("/login")
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#F3F4F6]">
      <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 bg-[#0A1628] px-5 py-3 sm:px-6">
        <Link className="flex items-center gap-3" href="/gerencial">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-[#1168BD]">
            <Building2 className="h-5 w-5 text-white" />
          </span>
          <span>
            <span className="block text-sm font-bold text-white">Panel gerencial</span>
            <span className="block text-xs text-white/40">
              {config?.bank_name} · {config?.branch_name}
            </span>
          </span>
        </Link>
        <nav className="order-3 flex w-full gap-1 border-t border-white/10 pt-2 sm:order-none sm:w-auto sm:border-0 sm:pt-0">
          {nav.map((item) => {
            const active =
              item.href === "/gerencial" ? path === item.href : path.startsWith(item.href)
            const Icon = item.icon
            return (
              <Link
                className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition ${
                  active ? "bg-white/15 text-white" : "text-white/55 hover:bg-white/10"
                }`}
                href={item.href}
                key={item.href}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            )
          })}
        </nav>
        <div className="flex items-center gap-3">
          <p className="hidden text-sm text-white/60 md:block">{user?.email}</p>
          <button
            aria-label="Cerrar sesión"
            className="rounded-xl p-2 text-white/55 hover:bg-white/10 hover:text-white"
            onClick={exit}
            type="button"
          >
            <LogOut className="h-5 w-5" />
          </button>
        </div>
      </header>
      <main className="flex-1 p-4 sm:p-6">{children}</main>
    </div>
  )
}

export default function ManagerLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard roles={["MANAGER"]}>
      <ManagerShell>{children}</ManagerShell>
    </RoleGuard>
  )
}
