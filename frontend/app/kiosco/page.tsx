'use client'

import Link from 'next/link'
import { Clock } from '@/components/kiosk/clock'
import { Button } from '@/components/ui/button'
import { ArrowRight, Building2 } from 'lucide-react'

export default function KioscoPage() {
  return (
    <div className="flex-1 flex flex-col items-center justify-between py-12 px-8">
      {/* Logo placeholder */}
      <div className="flex flex-col items-center gap-4">
        <div className="w-24 h-24 rounded-2xl bg-[#1168BD]/20 border-2 border-[#1168BD]/40 flex items-center justify-center">
          <Building2 className="w-12 h-12 text-[#1168BD]" />
        </div>
        <div className="text-center">
          <p className="text-xl font-bold text-white tracking-wide">BANCO MERCANTIL SANTA CRUZ</p>
          <p className="text-white/40 text-sm mt-1">Sucursal Centro</p>
        </div>
      </div>

      {/* Main message */}
      <div className="flex flex-col items-center gap-6 text-center">
        <h1 className="text-5xl font-light text-white leading-tight">
          Bienvenido al Sistema de<br />
          <span className="font-bold text-[#23A2D9]">Atención Inteligente</span>
        </h1>
        <p className="text-xl text-white/60">Presione el botón para iniciar su atención</p>

        <Link href="/kiosco/voz">
          <Button variant="primary" size="xl" className="mt-4 gap-3 shadow-2xl shadow-[#1168BD]/40">
            Iniciar Atención
            <ArrowRight className="w-7 h-7" />
          </Button>
        </Link>
      </div>

      {/* Clock */}
      <Clock />
    </div>
  )
}
