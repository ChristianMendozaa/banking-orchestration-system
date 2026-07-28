"use client"

import { useKiosk, type VoiceState } from "@/components/providers/kiosk-provider"
import { TextInteraction } from "@/components/kiosk/text-interaction"
import { useSystemConfig } from "@/components/providers/system-config-provider"
import { Button } from "@/components/ui/button"
import {
  AudioLines,
  CircleAlert,
  LoaderCircle,
  Mic,
  Keyboard,
  RefreshCw,
  ShieldCheck,
  Volume2,
} from "lucide-react"
import { useEffect } from "react"

const statusText: Record<VoiceState, string> = {
  idle: "Estoy preparando nuestra conversación…",
  connecting: "Estoy conectando el canal seguro…",
  listening: "Te escucho",
  thinking: "Estoy revisando lo que me contaste…",
  speaking: "Te estoy respondiendo",
  muted: "Micrófono pausado",
  error: "Necesitamos reconectar la conversación",
  closed: "Atención finalizada",
}

export default function VoicePage() {
  const { config } = useSystemConfig()
  const {
    session,
    hydrated,
    analysis,
    voiceState,
    voiceError,
    captions,
    connectVoice,
    retryVoice,
    reset,
    interactionMode,
    selectInteractionMode,
  } = useKiosk()

  useEffect(() => {
    if (!hydrated || !session || interactionMode !== "voice") return
    if (voiceState === "idle") {
      void connectVoice().catch(() => {
        // El provider convierte el fallo en un estado recuperable visible.
      })
    }
  }, [connectVoice, hydrated, interactionMode, session, voiceState])

  function returnToStart() {
    reset()
  }

  if (!hydrated || !session) return null
  if (interactionMode === "text") return <TextInteraction />

  const recentCaptions = captions.slice(-6)
  const animated = voiceState === "listening" || voiceState === "speaking"

  return (
    <div className="flex flex-1 flex-col items-center gap-7 px-5 py-8 sm:px-8">
      <div className="max-w-3xl text-center">
        <p className="mb-3 inline-flex items-center gap-2 text-sm font-semibold uppercase tracking-widest text-[#23A2D9]">
          <Volume2 className="h-4 w-4" />
          Conversación en tiempo real
        </p>
        <h1 className="text-3xl font-light sm:text-4xl">
          {analysis?.next_action === "CLARIFY"
            ? "Necesito que me aclares un detalle"
            : analysis?.next_action === "CONFIRM"
              ? "Confírmame si entendí bien"
              : "¿En qué puedo ayudarte?"}
        </h1>
        <p className="mt-3 text-white/75">
          Habla con naturalidad. Puedes interrumpirme cuando lo necesites.
        </p>
        <Button
          className="mt-5"
          onClick={() => selectInteractionMode("text")}
          size="sm"
          variant="ghost"
        >
          <Keyboard className="h-4 w-4" />
          Prefiero escribir
        </Button>
      </div>

      <div className="relative my-2 grid h-44 w-44 place-items-center sm:h-52 sm:w-52">
        {animated && (
          <>
            <span className="absolute inset-0 animate-ping rounded-full bg-[#23A2D9]/15" />
            <span className="absolute inset-5 animate-pulse rounded-full bg-[#1168BD]/25" />
          </>
        )}
        <div
          className={`relative grid h-36 w-36 place-items-center rounded-full border sm:h-44 sm:w-44 ${
            voiceState === "error"
              ? "border-red-400/40 bg-red-500/15"
              : voiceState === "speaking"
                ? "border-[#7DD3FC]/50 bg-[#1168BD]"
                : "border-[#23A2D9]/35 bg-[#1168BD]/55"
          }`}
          aria-hidden
        >
          {voiceState === "connecting" || voiceState === "thinking" ? (
            <LoaderCircle className="h-16 w-16 animate-spin text-[#7DD3FC]" />
          ) : voiceState === "speaking" ? (
            <AudioLines className="h-16 w-16 text-white" />
          ) : voiceState === "error" ? (
            <CircleAlert className="h-16 w-16 text-red-300" />
          ) : (
            <Mic className="h-16 w-16 text-white" />
          )}
        </div>
      </div>

      <p className="text-lg font-medium text-white/70" role="status">
        {statusText[voiceState]}
      </p>

      {voiceError && (
        <section className="w-full max-w-xl rounded-2xl border border-red-400/30 bg-red-400/10 p-5 text-center">
          <p className="text-sm text-red-100" role="alert">
            {voiceError}
          </p>
          <div className="mt-4 flex flex-col justify-center gap-3 sm:flex-row">
            <Button onClick={() => void retryVoice()} size="lg">
              <RefreshCw className="h-5 w-5" />
              Reintentar
            </Button>
            <Button onClick={returnToStart} size="lg" variant="ghost">
              Volver al inicio y pedir ayuda
            </Button>
          </div>
        </section>
      )}

      {recentCaptions.length > 0 && (
        <section
          aria-label="Subtítulos de la conversación"
          className="w-full max-w-3xl space-y-3"
        >
          {recentCaptions.map((caption) => (
            <div
              className={`flex ${caption.role === "user" ? "justify-end" : "justify-start"}`}
              key={caption.id}
            >
              <div
                className={`max-w-[88%] rounded-2xl px-5 py-3 text-sm leading-relaxed sm:text-base ${
                  caption.role === "user"
                    ? "rounded-br-sm bg-[#1168BD] text-white"
                    : "rounded-bl-sm border border-white/10 bg-white/[.08] text-white/85"
                } ${caption.completed ? "" : "opacity-65"}`}
              >
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-white/70">
                  {caption.role === "user" ? "Tú" : "Asistente"}
                </p>
                {caption.text}
              </div>
            </div>
          ))}
        </section>
      )}

      <p className="mt-auto flex max-w-2xl items-center justify-center gap-2 text-center text-sm text-white/70">
        <ShieldCheck className="h-4 w-4 shrink-0" />
        No menciones contraseñas, PIN, CVV ni números financieros completos. El audio y la
        transcripción original no se guardan; los mensajes enmascarados se conservan
        {config?.conversation_retention_days
          ? ` ${config.conversation_retention_days} días.`
          : " durante el plazo de retención configurado."}
      </p>
    </div>
  )
}
