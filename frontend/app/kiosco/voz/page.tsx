"use client"

import { speak, useKiosk } from "@/components/providers/kiosk-provider"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Button } from "@/components/ui/button"
import { ApiError, errorMessage } from "@/lib/api"
import type { TurnAnalysis } from "@/lib/types"
import { Keyboard, Mic, MicOff, Send, StopCircle, Volume2 } from "lucide-react"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useRef, useState } from "react"

interface RealtimeSecret {
  value: string
  expires_at: number | null
}

interface RealtimeEvent {
  type?: string
  delta?: string
  transcript?: string
}

type VoicePhase = "idle" | "connecting" | "listening" | "stopping" | "submitting"

export default function VoicePage() {
  const { config } = useSystemConfig()
  const {
    session,
    hydrated,
    transcript,
    analysis,
    isClarification,
    setTranscript,
    setAnalysis,
    setIsClarification,
    sessionRequest,
    reset,
  } = useKiosk()
  const router = useRouter()
  const [phase, setPhase] = useState<VoicePhase>("idle")
  const [partial, setPartial] = useState("")
  const [error, setError] = useState<string | null>(null)
  const peerRef = useRef<RTCPeerConnection | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const channelRef = useRef<RTCDataChannel | null>(null)
  const finalTranscriptRef = useRef(transcript)

  useEffect(() => {
    finalTranscriptRef.current = transcript
  }, [transcript])

  const disconnect = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    channelRef.current?.close()
    peerRef.current?.close()
    streamRef.current = null
    channelRef.current = null
    peerRef.current = null
    setPartial("")
  }, [])

  useEffect(() => disconnect, [disconnect])

  useEffect(() => {
    if (hydrated && !session) router.replace("/kiosco")
  }, [hydrated, router, session])

  function handleRealtimeMessage(message: MessageEvent<string>) {
    try {
      const event = JSON.parse(message.data) as RealtimeEvent
      if (event.type === "conversation.item.input_audio_transcription.delta") {
        setPartial((current) => current + (event.delta ?? ""))
      }
      if (event.type === "conversation.item.input_audio_transcription.completed") {
        const completed = (event.transcript ?? "").trim()
        if (completed) {
          const merged = [finalTranscriptRef.current.trim(), completed].filter(Boolean).join(" ")
          finalTranscriptRef.current = merged
          setTranscript(merged)
        }
        setPartial("")
      }
      if (event.type === "error") {
        setError("El canal de voz informó un error. Puede continuar escribiendo su consulta.")
      }
    } catch {
      // Los eventos desconocidos del canal Realtime no afectan el flujo.
    }
  }

  async function startListening() {
    if (!session || phase !== "idle") return
    setError(null)
    setPartial("")
    setPhase("connecting")
    try {
      if (!config) {
        throw new Error("La configuración del sistema aún no está disponible")
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Este navegador no permite capturar audio")
      }
      const secret = await sessionRequest<RealtimeSecret>("/realtime-token", { method: "POST" })
      const peer = new RTCPeerConnection()
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      stream.getTracks().forEach((track) => peer.addTrack(track, stream))
      const channel = peer.createDataChannel("oai-events")
      channel.addEventListener("message", handleRealtimeMessage)
      peerRef.current = peer
      streamRef.current = stream
      channelRef.current = channel

      const offer = await peer.createOffer()
      await peer.setLocalDescription(offer)
      const realtimeResponse = await fetch("https://api.openai.com/v1/realtime/calls", {
        method: "POST",
        body: offer.sdp,
        headers: {
          Authorization: `Bearer ${secret.value}`,
          "Content-Type": "application/sdp",
        },
      })
      if (!realtimeResponse.ok) {
        throw new Error("No fue posible establecer el canal seguro de voz")
      }
      await peer.setRemoteDescription({
        type: "answer",
        sdp: await realtimeResponse.text(),
      })
      setPhase("listening")
    } catch (reason) {
      disconnect()
      setPhase("idle")
      if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
        reset()
        router.replace("/kiosco")
        return
      }
      setError(`${errorMessage(reason)}. Puede escribir su consulta en el campo inferior.`)
    }
  }

  async function stopListening() {
    if (phase !== "listening") return
    setPhase("stopping")
    streamRef.current?.getTracks().forEach((track) => track.stop())
    if (config?.voice_drain_ms) {
      await new Promise((resolve) => window.setTimeout(resolve, config.voice_drain_ms))
    }
    disconnect()
    setPhase("idle")
  }

  async function submitTurn() {
    const normalized = transcript.trim()
    if (normalized.length < 2 || phase !== "idle") return
    setError(null)
    setPhase("submitting")
    try {
      const response = await sessionRequest<TurnAnalysis>("/turns", {
        method: "POST",
        body: JSON.stringify({
          turn_id: crypto.randomUUID(),
          transcript: normalized,
          is_clarification: isClarification,
        }),
      })
      setAnalysis(response)
      speak(response.speech_text)
      if (response.next_action === "CLARIFY") {
        setIsClarification(true)
        setTranscript("")
      } else {
        setIsClarification(false)
        router.push("/kiosco/confirmacion")
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
        reset()
        router.replace("/kiosco")
        return
      }
      setError(errorMessage(reason))
    } finally {
      setPhase("idle")
    }
  }

  const busy = phase !== "idle"
  const listening = phase === "listening" || phase === "stopping"

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-7 px-5 py-8 sm:px-8">
      <div className="max-w-3xl text-center">
        {isClarification && analysis?.clarification_question ? (
          <>
            <p className="mb-3 inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-widest text-[#23A2D9]">
              <Volume2 className="h-4 w-4" />
              Necesito una aclaración
            </p>
            <h1 className="text-3xl font-light sm:text-4xl">{analysis.clarification_question}</h1>
          </>
        ) : (
          <>
            <h1 className="text-3xl font-light sm:text-4xl">
              Describa el motivo de su atención
            </h1>
            <p className="mt-3 text-white/50">
              No mencione contraseñas, PIN, CVV ni números financieros completos.
            </p>
          </>
        )}
      </div>

      <button
        aria-label={listening ? "Detener captura de voz" : "Iniciar captura de voz"}
        className={`grid h-36 w-36 place-items-center rounded-full transition sm:h-44 sm:w-44 ${
          listening
            ? "animate-mic-pulse bg-red-600"
            : "bg-[#1168BD] hover:scale-105 hover:bg-[#0d56a0]"
        } disabled:cursor-not-allowed disabled:opacity-50`}
        disabled={phase === "connecting" || phase === "submitting" || phase === "stopping"}
        onClick={listening ? stopListening : startListening}
        type="button"
      >
        {listening ? (
          <StopCircle className="h-16 w-16 sm:h-20 sm:w-20" />
        ) : phase === "connecting" ? (
          <span className="h-12 w-12 animate-spin rounded-full border-4 border-white/30 border-t-white" />
        ) : (
          <Mic className="h-16 w-16 sm:h-20 sm:w-20" />
        )}
      </button>

      <p className="text-lg text-white/60" role="status">
        {phase === "connecting" && "Conectando el canal seguro…"}
        {phase === "listening" && "Escuchando… pulse nuevamente al terminar"}
        {phase === "stopping" && "Finalizando la transcripción…"}
        {phase === "submitting" && "Analizando su requerimiento…"}
        {phase === "idle" && "Pulse el micrófono para hablar"}
      </p>

      {listening && (
        <div className="flex h-10 items-center gap-1" aria-hidden>
          {Array.from({ length: 14 }).map((_, index) => (
            <span
              className="animate-wave-bar w-1.5 rounded-full bg-[#23A2D9]"
              key={index}
              style={{ animationDelay: `${index * 0.07}s` }}
            />
          ))}
        </div>
      )}

      <div className="w-full max-w-3xl">
        <label className="mb-2 flex items-center gap-2 text-sm text-white/55" htmlFor="transcript">
          <Keyboard className="h-4 w-4" />
          Transcripción editable / alternativa por teclado
        </label>
        <textarea
          className="min-h-28 w-full resize-y rounded-2xl border border-white/15 bg-white/[.08] px-5 py-4 text-lg text-white outline-none placeholder:text-white/25 focus:border-[#23A2D9]"
          disabled={listening || phase === "submitting"}
          id="transcript"
          maxLength={4000}
          onChange={(event) => setTranscript(event.target.value)}
          placeholder={partial || "Su consulta aparecerá aquí; también puede escribirla."}
          value={transcript}
        />
        {partial && !transcript && <p className="mt-2 text-sm italic text-white/45">{partial}</p>}
        {error && (
          <p className="mt-3 rounded-xl border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200" role="alert">
            {error}
          </p>
        )}
        <div className="mt-5 flex flex-wrap justify-center gap-3">
          <Button
            disabled={busy || transcript.trim().length < 2}
            onClick={submitTurn}
            size="lg"
          >
            <Send className="h-5 w-5" />
            Enviar para análisis
          </Button>
          {listening && (
            <Button disabled={phase === "stopping"} onClick={stopListening} size="lg" variant="danger">
              <MicOff className="h-5 w-5" />
              Detener
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
