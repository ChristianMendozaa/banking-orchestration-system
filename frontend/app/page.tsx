"use client"

import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Building2, LayoutDashboard, Mic, ShieldCheck } from "lucide-react"
import Link from "next/link"

export default function HomePage() {
  const { config, loading, error } = useSystemConfig()

  return (
    <main className="min-h-screen bg-[#071426] px-6 py-12 text-white">
      <div className="mx-auto flex min-h-[calc(100vh-6rem)] max-w-5xl flex-col justify-between">
        <header className="flex items-center gap-4">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-[#1168BD]">
            <Building2 aria-hidden className="h-7 w-7" />
          </div>
          <div>
            <p className="font-semibold">{config?.bank_name ?? "Cargando configuración…"}</p>
            <p className="text-sm text-white/45">{config?.branch_name ?? ""}</p>
          </div>
        </header>

        <section className="py-16">
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#23A2D9]/30 bg-[#23A2D9]/10 px-4 py-2 text-sm text-[#7DD3FC]">
            <ShieldCheck className="h-4 w-4" />
            Prototipo funcional en entorno controlado
          </div>
          <h1 className="max-w-3xl text-4xl font-bold leading-tight sm:text-6xl">
            {config?.app_name ?? "Sistema de Orquestación Bancaria"}
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-white/60">
            Atención inicial por voz, clasificación, priorización, derivación y seguimiento
            operativo en un flujo integrado.
          </p>
          {error && (
            <p className="mt-4 rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">
              No se pudo cargar la configuración: {error}
            </p>
          )}
        </section>

        <section className="grid gap-4 pb-8 md:grid-cols-2" aria-busy={loading}>
          <Link
            href="/kiosco"
            className="group rounded-3xl border border-white/10 bg-white/[.06] p-7 transition hover:border-[#23A2D9]/50 hover:bg-white/[.09]"
          >
            <Mic className="mb-5 h-9 w-9 text-[#23A2D9]" />
            <h2 className="text-2xl font-semibold">Iniciar atención</h2>
            <p className="mt-2 text-white/55">
              Acceso público al kiosco guiado por voz y texto.
            </p>
          </Link>
          <Link
            href="/login"
            className="group rounded-3xl border border-white/10 bg-white/[.06] p-7 transition hover:border-[#1168BD]/70 hover:bg-white/[.09]"
          >
            <LayoutDashboard className="mb-5 h-9 w-9 text-[#60A5FA]" />
            <h2 className="text-2xl font-semibold">Acceso del personal</h2>
            <p className="mt-2 text-white/55">
              Panel operativo para ejecutivos y panel gerencial.
            </p>
          </Link>
        </section>
      </div>
    </main>
  )
}
