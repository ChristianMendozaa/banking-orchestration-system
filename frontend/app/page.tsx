import Link from 'next/link'
import { Building2, Monitor, Mic, CheckSquare, MessageSquare, Ticket, LayoutDashboard, FolderSearch, BarChart3, ArrowRight } from 'lucide-react'

const kioskScreens = [
  { href: '/kiosco', label: 'Pantalla de Bienvenida', description: 'Inicio del flujo en el kiosco de autoatención', icon: Monitor, color: '#1168BD' },
  { href: '/kiosco/voz', label: 'Captura de Voz', description: 'Micrófono animado y transcripción en tiempo real', icon: Mic, color: '#23A2D9' },
  { href: '/kiosco/confirmacion', label: 'Confirmación de Consulta', description: 'Verificación de categoría y prioridad detectada', icon: CheckSquare, color: '#F59E0B' },
  { href: '/kiosco/respuesta', label: 'Respuesta Automática', description: 'Resolución inmediata para casos simples', icon: MessageSquare, color: '#10B981' },
  { href: '/kiosco/ticket', label: 'Ticket Asignado', description: 'Derivación a ejecutivo especializado', icon: Ticket, color: '#8B5CF6' },
]

const executiveScreens = [
  { href: '/ejecutivo', label: 'Dashboard Ejecutivo', description: '5 casos activos con categorías, prioridades y tiempo de espera', icon: LayoutDashboard, color: '#1168BD' },
  { href: '/ejecutivo/caso/2031', label: 'Detalle de Caso', description: 'Trazabilidad, gestión de estado y datos del cliente', icon: FolderSearch, color: '#23A2D9' },
  { href: '/gerencial', label: 'Dashboard Gerencial', description: 'KPIs, gráficos recharts y tabla de los últimos 10 casos', icon: BarChart3, color: '#EF4444' },
]

export default function IndexPage() {
  return (
    <div className="min-h-screen bg-[#F3F4F6]">
      {/* Header */}
      <header className="bg-[#0A1628] py-10 px-6">
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-[#1168BD] flex items-center justify-center">
            <Building2 className="w-7 h-7 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Sistema de Orquestación Bancaria</h1>
            <p className="text-white/50 text-sm mt-0.5">Banco Mercantil Santa Cruz — Índice de pantallas</p>
          </div>
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-6 py-10 flex flex-col gap-10">
        {/* Kiosk section */}
        <section>
          <div className="flex items-center gap-3 mb-4">
            <Monitor className="w-5 h-5 text-[#1168BD]" />
            <h2 className="text-lg font-bold text-gray-900">Pantallas del Kiosco</h2>
            <span className="text-xs bg-[#1168BD]/10 text-[#1168BD] px-2 py-0.5 rounded-full font-semibold">Táctil / Tablet</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {kioskScreens.map((screen) => {
              const Icon = screen.icon
              return (
                <Link
                  key={screen.href}
                  href={screen.href}
                  className="bg-white rounded-2xl border border-gray-100 p-5 flex flex-col gap-3 hover:shadow-md hover:border-[#1168BD]/20 transition-all group"
                >
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ backgroundColor: `${screen.color}18` }}
                  >
                    <Icon className="w-5 h-5" style={{ color: screen.color }} />
                  </div>
                  <div>
                    <p className="font-semibold text-gray-900 group-hover:text-[#1168BD] transition-colors">{screen.label}</p>
                    <p className="text-sm text-gray-400 mt-0.5 leading-snug">{screen.description}</p>
                  </div>
                  <div className="flex items-center gap-1 text-xs text-gray-300 group-hover:text-[#1168BD] transition-colors mt-auto">
                    <span>{screen.href}</span>
                    <ArrowRight className="w-3 h-3" />
                  </div>
                </Link>
              )
            })}
          </div>
        </section>

        {/* Executive / Managerial section */}
        <section>
          <div className="flex items-center gap-3 mb-4">
            <LayoutDashboard className="w-5 h-5 text-[#1168BD]" />
            <h2 className="text-lg font-bold text-gray-900">Pantallas de Back-Office</h2>
            <span className="text-xs bg-[#23A2D9]/10 text-[#23A2D9] px-2 py-0.5 rounded-full font-semibold">Escritorio</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {executiveScreens.map((screen) => {
              const Icon = screen.icon
              return (
                <Link
                  key={screen.href}
                  href={screen.href}
                  className="bg-white rounded-2xl border border-gray-100 p-5 flex flex-col gap-3 hover:shadow-md hover:border-[#1168BD]/20 transition-all group"
                >
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ backgroundColor: `${screen.color}18` }}
                  >
                    <Icon className="w-5 h-5" style={{ color: screen.color }} />
                  </div>
                  <div>
                    <p className="font-semibold text-gray-900 group-hover:text-[#1168BD] transition-colors">{screen.label}</p>
                    <p className="text-sm text-gray-400 mt-0.5 leading-snug">{screen.description}</p>
                  </div>
                  <div className="flex items-center gap-1 text-xs text-gray-300 group-hover:text-[#1168BD] transition-colors mt-auto">
                    <span>{screen.href}</span>
                    <ArrowRight className="w-3 h-3" />
                  </div>
                </Link>
              )
            })}
          </div>
        </section>

        <footer className="text-center text-xs text-gray-400 py-4 border-t border-gray-200">
          Sistema de Orquestación — Prototipo UI · Banco Mercantil Santa Cruz · {new Date().getFullYear()}
        </footer>
      </div>
    </div>
  )
}
