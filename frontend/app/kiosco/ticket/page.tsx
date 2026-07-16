'use client'

import Link from 'next/link'
import { MapPin, User, Shield, Clock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

export default function TicketPage() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-12">
      <div className="w-full max-w-2xl flex flex-col items-center gap-8">
        {/* Ticket number */}
        <div className="text-center">
          <p className="text-white/50 text-sm uppercase tracking-widest mb-2">Su número de atención</p>
          <p className="text-8xl font-bold text-white tabular-nums">#2031</p>
        </div>

        {/* Status banner */}
        <div className="w-full bg-[#1168BD]/15 border border-[#1168BD]/30 rounded-2xl px-6 py-4 text-center">
          <p className="text-[#23A2D9] font-medium text-lg">
            Su caso ha sido derivado a un ejecutivo especializado
          </p>
        </div>

        {/* Executive card */}
        <div className="w-full bg-white/8 border border-white/15 rounded-2xl p-6 flex flex-col gap-5">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className="w-14 h-14 rounded-full bg-[#1168BD]/30 border-2 border-[#1168BD]/50 flex items-center justify-center">
                <User className="w-7 h-7 text-[#23A2D9]" />
              </div>
              <div>
                <p className="text-white font-semibold text-xl">Lic. María Fernández</p>
                <p className="text-white/50 flex items-center gap-1.5 mt-0.5">
                  <Shield className="w-4 h-4" />
                  Tarjetas y Seguridad
                </p>
              </div>
            </div>
            <Badge variant="ALTO">ALTA</Badge>
          </div>

          <div className="flex flex-wrap gap-6 pt-2 border-t border-white/10">
            <div className="flex items-center gap-2 text-[#23A2D9]">
              <MapPin className="w-5 h-5" />
              <span className="font-semibold text-lg">Ventanilla 3</span>
            </div>
            <div className="flex items-center gap-2 text-white/50">
              <Clock className="w-5 h-5" />
              <span>Tiempo estimado: 5–10 min</span>
            </div>
          </div>
        </div>

        {/* Case summary */}
        <div className="w-full bg-white/5 border border-white/10 rounded-xl px-5 py-4">
          <p className="text-xs uppercase tracking-widest text-white/30 mb-2">Resumen del caso</p>
          <p className="text-white/80">Bloqueo de tarjeta de débito por extravío reportado esta mañana</p>
        </div>

        <p className="text-white/40 text-sm text-center">
          Por favor dirígase a la ventanilla asignada con su número de atención
        </p>

        <Link href="/kiosco">
          <Button variant="primary" size="xl">Finalizar atención</Button>
        </Link>
      </div>
    </div>
  )
}
