'use client'

import Link from 'next/link'
import { CheckCircle, MessageSquare, Ticket } from 'lucide-react'
import { Button } from '@/components/ui/button'

const AUTO_RESPONSE = `Los horarios de atención de nuestras sucursales son:

• Lunes a Viernes: 08:30 – 16:00
• Sábados: 09:00 – 12:30
• Domingos y feriados: Cerrado

Puede realizar operaciones bancarias en nuestra banca en línea las 24 horas del día. También puede consultar el horario específico de cualquier sucursal en nuestra aplicación móvil.`

export default function RespuestaPage() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-12">
      <div className="w-full max-w-2xl flex flex-col items-center gap-8">
        {/* Success icon */}
        <div className="flex flex-col items-center gap-3">
          <div className="w-20 h-20 rounded-full bg-green-500/15 border-2 border-green-400/40 flex items-center justify-center">
            <CheckCircle className="w-10 h-10 text-green-400" />
          </div>
          <p className="text-2xl font-semibold text-green-400">Su consulta ha sido resuelta</p>
          <p className="text-white/50 text-center text-sm">No necesita pasar por ventanilla</p>
        </div>

        {/* Chat bubble */}
        <div className="w-full">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-full bg-[#1168BD] flex items-center justify-center shrink-0 mt-1">
              <MessageSquare className="w-5 h-5 text-white" />
            </div>
            <div className="bg-white/10 border border-white/15 rounded-2xl rounded-tl-none px-6 py-5 flex-1">
              <p className="text-xs uppercase tracking-widest text-[#23A2D9] mb-3 font-semibold">
                Asistente Virtual — Banco Mercantil Santa Cruz
              </p>
              <p className="text-white/90 text-base leading-relaxed whitespace-pre-line">
                {AUTO_RESPONSE}
              </p>
            </div>
          </div>
        </div>

        {/* Ticket reference */}
        <div className="flex items-center gap-3 bg-white/8 border border-white/15 rounded-xl px-6 py-4">
          <Ticket className="w-5 h-5 text-[#23A2D9]" />
          <div>
            <p className="text-white/50 text-xs uppercase tracking-wide">Número de referencia</p>
            <p className="text-white font-bold text-lg">Ticket #2847</p>
          </div>
        </div>

        <Link href="/kiosco">
          <Button variant="primary" size="xl">Finalizar</Button>
        </Link>
      </div>
    </div>
  )
}
