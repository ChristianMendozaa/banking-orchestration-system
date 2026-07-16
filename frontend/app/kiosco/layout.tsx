export default function KioscoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0A1628] text-white flex flex-col">
      <header className="flex items-center justify-between px-8 py-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#1168BD] flex items-center justify-center">
            <span className="text-white font-bold text-sm">B</span>
          </div>
          <span className="text-white/60 text-sm font-medium tracking-wide uppercase">
            Banco Mercantil Santa Cruz
          </span>
        </div>
        <span className="text-white/30 text-xs">Sistema de Atención Inteligente</span>
      </header>
      <main className="flex-1 flex flex-col">{children}</main>
    </div>
  )
}
