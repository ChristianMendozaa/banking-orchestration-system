import { Building2, LogOut } from 'lucide-react'
import Link from 'next/link'

export default function GerencialLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#F3F4F6] flex flex-col">
      <header className="bg-[#0A1628] h-16 flex items-center justify-between px-6 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#1168BD] flex items-center justify-center">
            <Building2 className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-white font-bold text-sm leading-none">Dashboard Gerencial — Sucursal Centro</p>
            <p className="text-white/40 text-xs mt-0.5">Banco Mercantil Santa Cruz</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="hidden sm:block text-right">
            <p className="text-white text-sm font-semibold leading-none">Gerente de Sucursal</p>
            <p className="text-white/40 text-xs mt-0.5">Sucursal Centro — La Paz</p>
          </div>
          <Link
            href="/"
            className="flex items-center gap-2 text-white/60 hover:text-white text-sm transition-colors"
          >
            <LogOut className="w-4 h-4" />
          </Link>
        </div>
      </header>
      <main className="flex-1 p-6">{children}</main>
    </div>
  )
}
