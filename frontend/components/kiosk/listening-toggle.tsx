"use client"

import { useKiosk } from "@/components/providers/kiosk-provider"
import { Button } from "@/components/ui/button"
import { Mic, MicOff } from "lucide-react"

// Lets a customer stop the kiosk from hearing them -- someone talking beside them, a moment
// to think -- without ending the conversation. The provider decides when this is allowed:
// while the CI field is open the microphone stays shut and the control is not offered.
export function ListeningToggle() {
  const { listeningControlAvailable, listeningPaused, setListeningPaused } = useKiosk()

  if (!listeningControlAvailable) return null

  return (
    <Button
      aria-pressed={listeningPaused}
      onClick={() => setListeningPaused(!listeningPaused)}
      size="lg"
      type="button"
      variant={listeningPaused ? "primary" : "ghost"}
    >
      {listeningPaused ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />}
      {listeningPaused ? "Reanudar escucha" : "Pausar escucha"}
    </Button>
  )
}
