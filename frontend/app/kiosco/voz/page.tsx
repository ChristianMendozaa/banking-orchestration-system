'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { Mic, StopCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'

const MOCK_TRANSCRIPTION = 'Quiero bloquear mi tarjeta de débito, la perdí esta mañana'

export default function VozPage() {
  const [transcription, setTranscription] = useState('')

  useEffect(() => {
    const t1 = setTimeout(() => setTranscription('Quiero bloquear mi tarjeta de débito...'), 1500)
    const t2 = setTimeout(() => setTranscription(MOCK_TRANSCRIPTION), 3200)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [])

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-10 px-8 py-12">
      {/* Animated microphone */}
      <div className="flex flex-col items-center gap-8">
        <div className="animate-mic-pulse w-40 h-40 rounded-full bg-[#1168BD] flex items-center justify-center">
          <Mic className="w-20 h-20 text-white" />
        </div>

        <p className="text-3xl text-white/80 font-light text-center">
          Estoy escuchando… describa su consulta
        </p>
      </div>

      {/* Waveform */}
      <div className="flex items-center gap-1.5 h-12">
        {Array.from({ length: 18 }).map((_, i) => (
          <div
            key={i}
            className="animate-wave-bar w-2 rounded-full bg-[#23A2D9]"
            style={{ animationDelay: `${i * 0.07}s` }}
          />
        ))}
      </div>

      {/* Transcription */}
      <div className="w-full max-w-2xl min-h-[80px]">
        {transcription && (
          <div className="animate-fade-in bg-white/10 rounded-2xl px-6 py-4 border border-white/20">
            <p className="text-xs uppercase tracking-widest text-white/40 mb-2">Transcripción</p>
            <p className="text-white text-xl font-light italic">&quot;{transcription}&quot;</p>
          </div>
        )}
      </div>

      {/* Stop button */}
      <Link href="/kiosco/confirmacion">
        <Button variant="ghost" size="lg" className="gap-3">
          <StopCircle className="w-6 h-6" />
          Detener y confirmar
        </Button>
      </Link>
    </div>
  )
}
