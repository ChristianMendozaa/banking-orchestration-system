"use client"

import { Button } from "@/components/ui/button"
import { useEffect } from "react"

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error("Error de interfaz", { digest: error.digest })
  }, [error])

  return (
    <main
      className="grid min-h-screen place-items-center bg-[#071426] p-6 text-white"
      id="main-content"
    >
      <section className="max-w-lg rounded-3xl border border-white/15 bg-white/[.08] p-8 text-center">
        <h1 className="text-3xl font-bold">No pudimos mostrar esta pantalla</h1>
        <p className="mt-4 leading-relaxed text-white/80">
          Tus datos no se perdieron. Intenta cargar nuevamente y, si el problema continúa,
          solicita apoyo al personal de la sucursal.
        </p>
        <Button className="mt-7" onClick={reset} size="lg">
          Reintentar
        </Button>
      </section>
    </main>
  )
}
