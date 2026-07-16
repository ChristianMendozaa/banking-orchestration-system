import { SidebarNav } from '@/components/executive/sidebar-nav'
import { Bell, Building2 } from 'lucide-react'

export default function EjecutivoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#F3F4F6] flex flex-col">
      {/* Top navbar */}
      <header className="bg-white border-b border-gray-200 h-16 flex items-center justify-between px-6 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#0A1628] flex items-center justify-center">
            <Building2 className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-bold text-gray-900 leading-none">Banco Mercantil Santa Cruz</p>
            <p className="text-xs text-gray-400 mt-0.5">Sistema de Orquestación</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button className="relative p-2 rounded-xl hover:bg-gray-100 transition-colors">
            <Bell className="w-5 h-5 text-gray-500" />
            <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full" />
          </button>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-[#1168BD] flex items-center justify-center">
              <span className="text-white text-sm font-bold">CM</span>
            </div>
            <div className="hidden sm:block">
              <p className="text-sm font-semibold text-gray-900 leading-none">Lic. Carlos Mamani</p>
              <p className="text-xs text-gray-400 mt-0.5">Ejecutivo de Atención</p>
            </div>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <aside className="w-60 bg-white border-r border-gray-200 flex flex-col shrink-0">
          <SidebarNav />
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto p-6">
          {children}
        </main>
      </div>
    </div>
  )
}
