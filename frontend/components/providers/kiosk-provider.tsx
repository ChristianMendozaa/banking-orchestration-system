"use client"

import { RealtimeSession } from "@openai/agents/realtime"
import { useRouter } from "next/navigation"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { ApiError, apiRequest, errorMessage } from "@/lib/api"
import {
  captionsFromHistory,
  createKioskRealtimeAgent,
  requestControlledResponse,
  type ConversationCaption,
} from "@/lib/kiosk-realtime"
import type { FlowResult, KioskSession, TurnAnalysis } from "@/lib/types"

const STORAGE_KEY = "orquestacion_kiosk_flow_v3"
const LEGACY_STORAGE_KEYS = [
  "orquestacion_kiosk_flow_v1",
  "orquestacion_kiosk_flow_v2",
]
const COMPLETION_SECONDS = 20
const TERMINAL_AUDIO_TIMEOUT_MS = 30_000

export type VoiceState =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "muted"
  | "error"
  | "closed"

interface RealtimeSecret {
  value: string
  session?: {
    model?: string
  } | null
}

interface KioskState {
  session: KioskSession | null
  analysis: TurnAnalysis | null
  result: FlowResult | null
  isClarification: boolean
}

const emptyState: KioskState = {
  session: null,
  analysis: null,
  result: null,
  isClarification: false,
}

interface KioskContextValue extends KioskState {
  hydrated: boolean
  voiceState: VoiceState
  voiceError: string | null
  captions: ConversationCaption[]
  completionSeconds: number | null
  beginSession: (preferentialAttention: boolean) => Promise<void>
  connectVoice: () => Promise<void>
  retryVoice: () => Promise<void>
  submitIdentification: (identifier: string) => Promise<FlowResult>
  reset: () => void
}

const KioskContext = createContext<KioskContextValue | null>(null)

async function kioskSessionRequest<T>(
  session: KioskSession,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set("X-Session-Token", session.session_token)
  return apiRequest<T>(`/kiosk/sessions/${session.session_id}${path}`, {
    ...init,
    headers,
  })
}

function terminalInstructions(result: FlowResult): string {
  return `La operación terminó. Pronuncia fielmente este mensaje y una despedida breve: ${JSON.stringify(
    {
      speech_text: result.speech_text,
      resolution_type: result.resolution_type,
      ticket_number: result.ticket?.number ?? null,
      executive_name: result.executive?.name ?? null,
      window_number: result.executive?.window_number ?? null,
    },
  )}`
}

export function KioskProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [state, setState] = useState<KioskState>(emptyState)
  const [hydrated, setHydrated] = useState(false)
  const [voiceState, setVoiceState] = useState<VoiceState>("idle")
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [captions, setCaptions] = useState<ConversationCaption[]>([])
  const [completionSeconds, setCompletionSeconds] = useState<number | null>(null)

  const stateRef = useRef(state)
  const realtimeRef = useRef<RealtimeSession | null>(null)
  const connectPromiseRef = useRef<Promise<void> | null>(null)
  const connectionAttemptRef = useRef(0)
  const clarificationRef = useRef(false)
  const terminalPendingRef = useRef(false)
  const terminalAudioStartedRef = useRef(false)
  const turnIdsRef = useRef(new Map<string, string>())
  const completionIntervalRef = useRef<number | null>(null)
  const terminalAudioTimeoutRef = useRef<number | null>(null)

  const updateState = useCallback((updater: (current: KioskState) => KioskState) => {
    const next = updater(stateRef.current)
    stateRef.current = next
    setState(next)
  }, [])

  const clearTimers = useCallback(() => {
    if (completionIntervalRef.current !== null) {
      window.clearInterval(completionIntervalRef.current)
      completionIntervalRef.current = null
    }
    if (terminalAudioTimeoutRef.current !== null) {
      window.clearTimeout(terminalAudioTimeoutRef.current)
      terminalAudioTimeoutRef.current = null
    }
  }, [])

  const disposeRealtime = useCallback(() => {
    connectionAttemptRef.current += 1
    const realtime = realtimeRef.current
    realtimeRef.current = null
    connectPromiseRef.current = null
    if (realtime) {
      try {
        realtime.close()
      } catch {
        // La conexión puede haber sido cerrada previamente por el transporte.
      }
    }
    turnIdsRef.current.clear()
  }, [])

  const reset = useCallback(() => {
    clearTimers()
    disposeRealtime()
    clarificationRef.current = false
    terminalPendingRef.current = false
    terminalAudioStartedRef.current = false
    setCaptions([])
    setVoiceError(null)
    setVoiceState("idle")
    setCompletionSeconds(null)
    updateState(() => emptyState)
  }, [clearTimers, disposeRealtime, updateState])

  const startCompletionCountdown = useCallback(() => {
    if (completionIntervalRef.current !== null) return

    terminalPendingRef.current = false
    terminalAudioStartedRef.current = false
    if (terminalAudioTimeoutRef.current !== null) {
      window.clearTimeout(terminalAudioTimeoutRef.current)
      terminalAudioTimeoutRef.current = null
    }
    try {
      realtimeRef.current?.mute(true)
    } catch {
      // El cierre posterior garantiza que el micrófono quede liberado.
    }
    disposeRealtime()
    setVoiceState("closed")
    setCompletionSeconds(COMPLETION_SECONDS)

    let remaining = COMPLETION_SECONDS
    completionIntervalRef.current = window.setInterval(() => {
      remaining -= 1
      setCompletionSeconds(remaining)
      if (remaining > 0) return

      if (completionIntervalRef.current !== null) {
        window.clearInterval(completionIntervalRef.current)
        completionIntervalRef.current = null
      }
      reset()
      router.replace("/kiosco")
    }, 1_000)
  }, [disposeRealtime, reset, router])

  const armTerminalCompletion = useCallback(() => {
    terminalPendingRef.current = true
    terminalAudioStartedRef.current = false
    if (terminalAudioTimeoutRef.current !== null) {
      window.clearTimeout(terminalAudioTimeoutRef.current)
    }
    terminalAudioTimeoutRef.current = window.setTimeout(
      startCompletionCountdown,
      TERMINAL_AUDIO_TIMEOUT_MS,
    )
  }, [startCompletionCountdown])

  useEffect(() => {
    queueMicrotask(() => {
      for (const key of LEGACY_STORAGE_KEYS) sessionStorage.removeItem(key)
      const raw = sessionStorage.getItem(STORAGE_KEY)
      if (raw) {
        try {
          const restored = JSON.parse(raw) as KioskState
          if (restored.session && new Date(restored.session.expires_at) > new Date()) {
            stateRef.current = restored
            clarificationRef.current = restored.isClarification
            setState(restored)
          } else {
            sessionStorage.removeItem(STORAGE_KEY)
          }
        } catch {
          sessionStorage.removeItem(STORAGE_KEY)
        }
      }
      setHydrated(true)
    })
  }, [])

  useEffect(() => {
    if (!hydrated) return
    if (state.session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    else sessionStorage.removeItem(STORAGE_KEY)
  }, [hydrated, state])

  useEffect(() => {
    if (
      hydrated &&
      state.result?.next_action === "COMPLETE" &&
      completionSeconds === null &&
      (voiceState === "idle" || voiceState === "error")
    ) {
      startCompletionCountdown()
    }
  }, [
    completionSeconds,
    hydrated,
    startCompletionCountdown,
    state.result,
    voiceState,
  ])

  useEffect(
    () => () => {
      clearTimers()
      disposeRealtime()
    },
    [clearTimers, disposeRealtime],
  )

  const beginSession = useCallback(
    async (preferentialAttention: boolean) => {
      clearTimers()
      disposeRealtime()
      setCaptions([])
      setVoiceError(null)
      setVoiceState("idle")
      setCompletionSeconds(null)
      clarificationRef.current = false
      terminalPendingRef.current = false
      terminalAudioStartedRef.current = false
      updateState(() => emptyState)
      const session = await apiRequest<KioskSession>("/kiosk/sessions", {
        method: "POST",
        body: JSON.stringify({ preferential_attention: preferentialAttention }),
      })
      updateState(() => ({ ...emptyState, session }))
    },
    [clearTimers, disposeRealtime, updateState],
  )

  const handleExpiredSession = useCallback(() => {
    reset()
    router.replace("/kiosco")
  }, [reset, router])

  const connectVoice = useCallback(async () => {
    const current = realtimeRef.current
    if (current?.transport.status === "connected") return
    if (connectPromiseRef.current) return connectPromiseRef.current

    const activeSession = stateRef.current.session
    if (!activeSession) throw new Error("No existe una sesión activa")
    const attemptId = connectionAttemptRef.current + 1
    connectionAttemptRef.current = attemptId
    const isActiveAttempt = () =>
      attemptId === connectionAttemptRef.current &&
      stateRef.current.session?.session_id === activeSession.session_id

    const connection = (async () => {
      setVoiceError(null)
      setVoiceState("connecting")

      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Este navegador no permite capturar audio")
        }

        const secret = await kioskSessionRequest<RealtimeSecret>(
          activeSession,
          "/realtime-token",
          { method: "POST" },
        )
        if (attemptId !== connectionAttemptRef.current) return

        const agent = createKioskRealtimeAgent({
          analyzeRequirement: async (transcript, callId) => {
            const key = callId ?? crypto.randomUUID()
            let turnId = turnIdsRef.current.get(key)
            if (!turnId) {
              turnId = crypto.randomUUID()
              turnIdsRef.current.set(key, turnId)
            }

            try {
              const response = await kioskSessionRequest<TurnAnalysis>(
                activeSession,
                "/turns",
                {
                  method: "POST",
                  body: JSON.stringify({
                    turn_id: turnId,
                    transcript,
                    is_clarification: clarificationRef.current,
                  }),
                },
              )
              if (!isActiveAttempt()) return response
              setVoiceError(null)
              const isClarification = response.next_action === "CLARIFY"
              clarificationRef.current = isClarification
              updateState((stored) => ({
                ...stored,
                analysis: response,
                result: null,
                isClarification,
              }))
              return response
            } catch (reason) {
              if (!isActiveAttempt()) {
                throw reason
              } else if (
                reason instanceof ApiError &&
                reason.code === "SESSION_EXPIRED"
              ) {
                handleExpiredSession()
              } else {
                setVoiceError(errorMessage(reason))
                setVoiceState("error")
              }
              throw reason
            }
          },
          confirmRequirement: async (confirmed) => {
            try {
              const response = await kioskSessionRequest<FlowResult>(
                activeSession,
                "/confirmation",
                {
                  method: "POST",
                  body: JSON.stringify({ confirmed }),
                },
              )
              if (!isActiveAttempt()) return response
              setVoiceError(null)

              if (!confirmed || response.next_action === "CAPTURE") {
                clarificationRef.current = false
                updateState((stored) => ({
                  ...stored,
                  analysis: null,
                  result: null,
                  isClarification: false,
                }))
                return response
              }

              updateState((stored) => ({ ...stored, result: response }))
              if (response.next_action === "IDENTIFY") {
                try {
                  realtimeRef.current?.mute(true)
                } catch {
                  // WebRTC soporta mute; si ya se cerró, la pantalla seguirá protegida.
                }
                setVoiceState("muted")
                router.push("/kiosco/identificacion")
              } else if (response.next_action === "COMPLETE") {
                try {
                  realtimeRef.current?.mute(true)
                } catch {
                  // El resultado visual y el cierre temporizado permanecen disponibles.
                }
                armTerminalCompletion()
                router.push(
                  response.resolution_type === "AUTOMATIC"
                    ? "/kiosco/respuesta"
                    : "/kiosco/ticket",
                )
              }
              return response
            } catch (reason) {
              if (!isActiveAttempt()) {
                throw reason
              } else if (
                reason instanceof ApiError &&
                reason.code === "SESSION_EXPIRED"
              ) {
                handleExpiredSession()
              } else {
                setVoiceError(errorMessage(reason))
                setVoiceState("error")
              }
              throw reason
            }
          },
        })

        const realtime = new RealtimeSession(agent, {
          model: secret.session?.model ?? "gpt-realtime-2.1-mini",
          historyStoreAudio: false,
          tracingDisabled: true,
          config: {
            outputModalities: ["audio"],
            parallelToolCalls: false,
            reasoning: { effort: "low" },
            audio: {
              input: {
                noiseReduction: { type: "near_field" },
                transcription: {
                  model: "gpt-realtime-whisper",
                  language: "es",
                },
                turnDetection: {
                  type: "semantic_vad",
                  eagerness: "auto",
                  createResponse: true,
                  interruptResponse: true,
                },
              },
              output: {
                voice: "marin",
              },
            },
          },
        })
        realtimeRef.current = realtime
        const isCurrentRealtime = () =>
          isActiveAttempt() && realtimeRef.current === realtime

        realtime.on("history_updated", (history) => {
          if (!isCurrentRealtime()) return
          setCaptions(captionsFromHistory(history))
        })
        realtime.on("agent_tool_start", () => {
          if (!isCurrentRealtime()) return
          setVoiceState("thinking")
        })
        realtime.on("audio_start", () => {
          if (!isCurrentRealtime()) return
          if (terminalPendingRef.current) terminalAudioStartedRef.current = true
          setVoiceState("speaking")
        })
        realtime.on("audio_stopped", () => {
          if (!isCurrentRealtime()) return
          if (terminalPendingRef.current && terminalAudioStartedRef.current) {
            startCompletionCountdown()
          } else {
            setVoiceState(realtime.muted ? "muted" : "listening")
          }
        })
        realtime.on("audio_interrupted", () => {
          if (!isCurrentRealtime()) return
          if (terminalPendingRef.current && terminalAudioStartedRef.current) {
            startCompletionCountdown()
          } else {
            setVoiceState(realtime.muted ? "muted" : "listening")
          }
        })
        realtime.on("transport_event", (event) => {
          if (!isCurrentRealtime()) return
          if (event.type === "input_audio_buffer.speech_started") {
            setVoiceState("listening")
          } else if (event.type === "input_audio_buffer.speech_stopped") {
            setVoiceState("thinking")
          }
        })
        realtime.on("error", ({ error }) => {
          if (!isCurrentRealtime()) return
          setVoiceError(errorMessage(error))
          setVoiceState("error")
        })
        realtime.transport.on("connection_change", (status) => {
          if (
            status === "disconnected" &&
            realtimeRef.current === realtime
          ) {
            setVoiceError("Se perdió la conexión de voz")
            if (terminalPendingRef.current) {
              startCompletionCountdown()
            } else {
              setVoiceState("error")
            }
          }
        })

        await realtime.connect({ apiKey: secret.value })
        if (attemptId !== connectionAttemptRef.current) return
        setVoiceState("listening")

        const snapshot = stateRef.current
        if (snapshot.result?.next_action === "IDENTIFY") {
          realtime.mute(true)
          setVoiceState("muted")
          router.replace("/kiosco/identificacion")
          requestControlledResponse(
            realtime,
            "Indica brevemente que el código de cliente debe escribirse en el campo protegido y no dictarse.",
          )
        } else if (snapshot.analysis?.next_action === "CONFIRM") {
          requestControlledResponse(
            realtime,
            `Reanuda la confirmación y pronuncia fielmente este mensaje: ${JSON.stringify(
              snapshot.analysis.speech_text,
            )}`,
          )
        } else if (snapshot.analysis?.next_action === "CLARIFY") {
          requestControlledResponse(
            realtime,
            `Reanuda la aclaración y pronuncia fielmente esta pregunta: ${JSON.stringify(
              snapshot.analysis.speech_text,
            )}`,
          )
        } else {
          requestControlledResponse(
            realtime,
            "Inicia ahora la atención: preséntate como asistente virtual y pregunta de forma breve el motivo de la visita. No llames herramientas hasta escuchar a la persona.",
          )
        }
      } catch (reason) {
        if (attemptId !== connectionAttemptRef.current) return
        disposeRealtime()
        if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
          handleExpiredSession()
          return
        }
        setVoiceError(errorMessage(reason))
        setVoiceState("error")
        throw reason
      }
    })()

    connectPromiseRef.current = connection
    try {
      await connection
    } finally {
      if (connectPromiseRef.current === connection) connectPromiseRef.current = null
    }
  }, [
    armTerminalCompletion,
    disposeRealtime,
    handleExpiredSession,
    router,
    startCompletionCountdown,
    updateState,
  ])

  const retryVoice = useCallback(async () => {
    disposeRealtime()
    setVoiceError(null)
    setVoiceState("idle")
    await connectVoice()
  }, [connectVoice, disposeRealtime])

  const submitIdentification = useCallback(
    async (identifier: string) => {
      const activeSession = stateRef.current.session
      if (!activeSession) throw new Error("No existe una sesión activa")

      try {
        const completed = await kioskSessionRequest<FlowResult>(
          activeSession,
          "/identification",
          {
            method: "POST",
            body: JSON.stringify({ identifier: identifier.trim() }),
          },
        )
        if (stateRef.current.session?.session_id !== activeSession.session_id) {
          return completed
        }
        updateState((stored) => ({ ...stored, result: completed }))
        router.replace(
          completed.resolution_type === "AUTOMATIC"
            ? "/kiosco/respuesta"
            : "/kiosco/ticket",
        )

        const realtime = realtimeRef.current
        if (realtime?.transport.status === "connected") {
          try {
            realtime.mute(true)
            setVoiceState("muted")
            armTerminalCompletion()
            requestControlledResponse(realtime, terminalInstructions(completed))
          } catch {
            setVoiceError(
              "No fue posible reproducir el cierre por voz; el resultado permanece en pantalla.",
            )
            startCompletionCountdown()
          }
        } else {
          setVoiceError(
            "La conexión de voz se cerró; el resultado permanece disponible en pantalla.",
          )
          startCompletionCountdown()
        }
        return completed
      } catch (reason) {
        if (
          stateRef.current.session?.session_id === activeSession.session_id &&
          reason instanceof ApiError &&
          reason.code === "SESSION_EXPIRED"
        ) {
          handleExpiredSession()
        }
        throw reason
      }
    },
    [
      armTerminalCompletion,
      handleExpiredSession,
      router,
      startCompletionCountdown,
      updateState,
    ],
  )

  const value = useMemo<KioskContextValue>(
    () => ({
      ...state,
      hydrated,
      voiceState,
      voiceError,
      captions,
      completionSeconds,
      beginSession,
      connectVoice,
      retryVoice,
      submitIdentification,
      reset,
    }),
    [
      beginSession,
      captions,
      completionSeconds,
      connectVoice,
      hydrated,
      reset,
      retryVoice,
      state,
      submitIdentification,
      voiceError,
      voiceState,
    ],
  )

  return <KioskContext.Provider value={value}>{children}</KioskContext.Provider>
}

export function useKiosk(): KioskContextValue {
  const value = useContext(KioskContext)
  if (!value) throw new Error("useKiosk requiere KioskProvider")
  return value
}
