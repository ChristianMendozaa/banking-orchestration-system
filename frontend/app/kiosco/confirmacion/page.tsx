'use client'

import Link from 'next/link'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

export default function ConfirmacionPage() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 py-12">
      <div className="w-full max-w-2xl flex flex-col gap-6">
        {/* Header */}
        <div className="text-center">
          <h2 className="text-3xl font-light text-white">¿Esto es lo que nos indicó?</h2>
          <p className="text-white/50 mt-2">Verifique la información antes de confirmar</p>
        </div>

        {/* Transcription card */}
        <div className="bg-white/8 border border-white/15 rounded-2xl p-6 flex flex-col gap-4">
          <p className="text-xs uppercase tracking-widest text-white/40">Entendí que desea:</p>
          <p className="text-white text-2xl font-light leading-snug">
            Bloqueo de tarjeta de débito por extravío
          </p>

          {/* Badges row */}
          <div className="flex flex-wrap gap-3 pt-2">
            <Badge variant="BLOQUEO_TARJETA" />
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wide bg-red-100 text-red-800">
              Prioridad: ALTA
            </span>
          </div>
        </div>

        {/* Privacy note */}
        <div className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/25 rounded-xl px-5 py-3">
          <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0" />
          <p className="text-yellow-200/80 text-sm">
            Los datos sensibles han sido protegidos y no serán almacenados
          </p>
        </div>

        {/* Privacy verified */}
        <div className="flex items-center gap-3 bg-green-500/10 border border-green-500/25 rounded-xl px-5 py-3">
          <CheckCircle2 className="w-5 h-5 text-green-400 shrink-0" />
          <p className="text-green-200/80 text-sm">
            Sesión anónima — su identidad no es requerida para este proceso
          </p>
        </div>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-4 pt-2">
          <Link href="/kiosco/ticket" className="flex-1">
            <Button variant="primary" size="xl" className="w-full">
              Confirmar
            </Button>
          </Link>
          <Link href="/kiosco/voz" className="flex-1">
            <Button variant="ghost" size="xl" className="w-full">
              Corregir
            </Button>
          </Link>
        </div>
      </div>
    </div>
  )
}
