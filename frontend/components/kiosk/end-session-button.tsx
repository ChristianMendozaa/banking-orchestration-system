"use client"

import { useKiosk } from "@/components/providers/kiosk-provider"
import { Button } from "@/components/ui/button"
import { LogOut } from "lucide-react"
import { useEffect, useRef, useState } from "react"

// A customer may change their mind or want to start over at any step. `reset` already tears
// down the voice session and clears the flow; the provider then routes back to the start.
// The confirmation exists because a kiosk screen gets touched by accident.
export function EndSessionButton() {
  const { session, hydrated, reset } = useKiosk()
  const [confirming, setConfirming] = useState(false)
  const continueRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!confirming) return
    continueRef.current?.focus()
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setConfirming(false)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [confirming])

  if (!hydrated || !session) return null

  function finish() {
    setConfirming(false)
    reset()
  }

  return (
    <>
      <Button onClick={() => setConfirming(true)} size="sm" type="button" variant="ghost">
        <LogOut className="h-4 w-4" />
        Finalizar atención
      </Button>
      {confirming && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 px-5">
          <div
            aria-describedby="end-session-description"
            aria-labelledby="end-session-title"
            aria-modal="true"
            className="w-full max-w-md rounded-3xl border border-white/15 bg-[#071426] p-7 text-center"
            role="alertdialog"
          >
            <h2 className="text-2xl font-semibold" id="end-session-title">
              ¿Deseas finalizar la atención?
            </h2>
            <p className="mt-3 text-white/75" id="end-session-description">
              Se cerrará la conversación y volverás al inicio. Si ya recibiste un ticket, sigue
              siendo válido.
            </p>
            <div className="mt-6 flex flex-col-reverse justify-center gap-3 sm:flex-row">
              <Button
                onClick={() => setConfirming(false)}
                ref={continueRef}
                type="button"
                variant="ghost"
              >
                Continuar
              </Button>
              <Button onClick={finish} type="button" variant="danger">
                Sí, finalizar
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
