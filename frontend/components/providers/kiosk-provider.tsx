"use client"

import type { RealtimeSession } from "@openai/agents/realtime"
import { usePathname, useRouter } from "next/navigation"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { ApiError, errorMessage } from "@/lib/api"
import {
  createKioskSession,
  kioskSessionRequest,
  type RealtimeSecret,
} from "@/lib/kiosk-api"
import {
  OUTAGE_GUIDANCE,
  SpeechFloor,
  analysisSpeechPlan,
  captionsFromHistory,
  captionsFromStoredConversation,
  correctedRequest,
  declineCanContinue,
  explicitConfirmation,
  fillerInstructions,
  greetingInstructions,
  isBenignRealtimeError,
  isConversationClose,
  isSessionExhausted,
  isSessionStateConflict,
  isSpeechFragment,
  isTerminalDecline,
  isTerminalFlowResult,
  kioskRouteForState,
  mergeConversationCaptions,
  microphoneShouldBeOpen,
  missingVerbatim,
  realtimeResponseId,
  realtimeVoiceSessionConfig,
  selectAuthoritativeTranscript,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  situationInstructions,
  turnInstructions,
  type ConversationCaption,
  type KioskTurnProcessingResult,
  type TranscriptSelection,
} from "@/lib/kiosk-realtime"
import type {
  ConversationHistory,
  FlowResult,
  KioskSession,
  KioskSessionStatus,
  SpeechPlan,
  TurnAnalysis,
} from "@/lib/types"
import { useOptionalSystemConfig } from "@/components/providers/system-config-provider"

const STORAGE_KEY = "orquestacion_kiosk_flow_v4"
const LEGACY_STORAGE_KEYS = [
  "orquestacion_kiosk_flow_v1",
  "orquestacion_kiosk_flow_v2",
  "orquestacion_kiosk_flow_v3",
]
const COMPLETION_SECONDS = 20
// How long the kiosk waits after a terminal handoff for the model to finish saying it,
// before it closes the session on its own.
const TERMINAL_AUDIO_TIMEOUT_MS = 30_000
// How long the kiosk keeps listening after answering a question by itself, before it
// finishes the session on its own. Longer than TERMINAL_AUDIO_TIMEOUT_MS: this one is
// waiting for a person to decide whether they have another question, not for audio to
// finish playing.
const DEFAULT_FOLLOW_UP_INACTIVITY_SECONDS = 20
// The same window while the customer has paused listening. Someone who paused is choosing
// to take their time, so the usual window would cut them off -- but a paused kiosk whose
// customer walked away still has to free itself for the next person.
const PAUSED_FOLLOW_UP_INACTIVITY_SECONDS = 120
// How long a lone word like "Quiero" waits for the rest of the sentence before it is sent to
// the bank on its own. See `isSpeechFragment`.
const FRAGMENT_HOLD_MS = 2_500
// How long the bank may take before the kiosk says "Un momento" so the silence does not read
// as the kiosk not having heard. Most turns answer well inside it and hear no filler at all.
const FILLER_DELAY_MS = 1_500
// How long one spoken turn may stay with the bank before the kiosk gives up on it and says
// so. Same ceiling the SDK's tool timeout used to impose when turns went through a tool.
const TURN_TIMEOUT_MS = 25_000

export type VoiceState =
  | "idle"
  | "connecting"
  | "listening"
  | "thinking"
  | "speaking"
  | "muted"
  | "error"
  | "closed"

export interface KioskState {
  session: KioskSession | null
  analysis: TurnAnalysis | null
  result: FlowResult | null
  isClarification: boolean
  interactionMode: "voice" | "text"
}

const emptyState: KioskState = {
  session: null,
  analysis: null,
  result: null,
  isClarification: false,
  interactionMode: "voice",
}

interface KioskContextValue extends KioskState {
  hydrated: boolean
  voiceState: VoiceState
  voiceError: string | null
  // The customer's own pause, distinct from the closures the business state imposes.
  listeningPaused: boolean
  // Whether the customer may pause or resume right now: only while the voice transport is
  // up and the business state would otherwise keep the microphone open.
  listeningControlAvailable: boolean
  setListeningPaused: (paused: boolean) => void
  captions: ConversationCaption[]
  completionSeconds: number | null
  beginSession: (preferentialAttention: boolean) => Promise<void>
  connectVoice: () => Promise<void>
  retryVoice: () => Promise<void>
  selectInteractionMode: (mode: "voice" | "text") => void
  noteUserActivity: () => void
  submitTextTurn: (transcript: string) => Promise<TurnAnalysis>
  confirmText: (confirmed: boolean) => Promise<FlowResult>
  submitIdentification: (identifier: string) => Promise<FlowResult>
  reset: () => void
}

const KioskContext = createContext<KioskContextValue | null>(null)

// Browser clock to browser clock, for the stages of one spoken turn. Subtracting a server
// timestamp from `performance.now()` would measure clock skew as much as anything else.
interface TurnTiming {
  // When the customer stopped talking, if the turn detector said so before the transcript.
  speechStoppedAt: number | null
  transcriptAt: number
  backendAt: number | null
}

// Deliberately a log line and not a metric endpoint: these are the numbers to look at while
// tuning the flow, and shipping per-session timings anywhere else would need a privacy
// decision this does not have. No transcript, no identifiers. Split by stage because the
// one total it used to log could not say whether a slow turn was the transcription, the
// bank, or the voice.
function reportTurnLatency(timing: TurnTiming, firstAudioAt: number): void {
  if (process.env.NODE_ENV === "production") return
  const backendAt = timing.backendAt ?? firstAudioAt
  console.info("[kiosco] tiempos del turno", {
    transcriptionMs:
      timing.speechStoppedAt === null
        ? null
        : Math.round(timing.transcriptAt - timing.speechStoppedAt),
    backendMs: Math.round(backendAt - timing.transcriptAt),
    voiceMs: Math.round(firstAudioAt - backendAt),
    totalMs: Math.round(firstAudioAt - (timing.speechStoppedAt ?? timing.transcriptAt)),
  })
}

// A short state summary handed to the model after a reconnect, so it can pick the
// conversation back up in its own words instead of the application replaying a script at it.
function resumeContext(state: KioskState): string | null {
  const { analysis, result } = state
  if (
    result?.resolution_type === "AUTOMATIC" &&
    result.conversation_can_continue
  ) {
    // Naming the topic is what lets the conversation continue rather than restart: someone
    // who reconnects mid-thread asks "¿y los sábados?" next, and a kiosk that only knows it
    // "answered a general query" has nothing to hand the backend for that.
    const topic = result.customer_summary?.trim()
    return topic
      ? `Se reconectó la voz. Acabas de responderle sobre esto: "${topic}". No lo repitas; pregunta brevemente si necesita algo más y sigue escuchando.`
      : "Se reconectó la voz después de responder una consulta general. Pregunta brevemente si necesita algo más y sigue escuchando."
  }
  if (result?.next_action === "CONFIRM" && result.customer_summary) {
    return `Se reconectó la voz. Estabas por confirmar esto: "${result.customer_summary}". Retómalo con una pregunta breve.`
  }
  if (result?.next_action === "IDENTIFY") {
    return "Se reconectó la voz. La persona debe escribir su CI en el campo protegido; recuérdaselo brevemente y espera."
  }
  if (result?.next_action === "CAPTURE") {
    return "Se reconectó la voz. La persona rechazó el resumen anterior; pídele que te cuente otra vez qué necesita."
  }
  if (analysis?.next_action === "CONFIRM" && analysis.customer_summary) {
    return `Se reconectó la voz. Estabas por confirmar esto: "${analysis.customer_summary}". Retómalo con una pregunta breve.`
  }
  if (analysis?.next_action === "CLARIFY" && analysis.clarification_question) {
    return `Se reconectó la voz. Te faltaba preguntar esto: "${analysis.clarification_question}". Retómalo.`
  }
  return null
}

export function KioskProvider({ children }: { children: React.ReactNode }) {
  const config = useOptionalSystemConfig()?.config ?? null
  const router = useRouter()
  const pathname = usePathname()
  const [state, setState] = useState<KioskState>(emptyState)
  const [hydrated, setHydrated] = useState(false)
  const [voiceState, setVoiceState] = useState<VoiceState>("idle")
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [captions, setCaptions] = useState<ConversationCaption[]>([])
  const [completionSeconds, setCompletionSeconds] = useState<number | null>(null)
  const [listeningPaused, setListeningPausedState] = useState(false)

  const stateRef = useRef(state)
  // Read by the microphone policy, which runs from callbacks that must not wait a render.
  const listeningPausedRef = useRef(false)
  const businessRevisionRef = useRef(0)
  const realtimeRef = useRef<RealtimeSession | null>(null)
  const connectPromiseRef = useRef<Promise<void> | null>(null)
  const connectionAttemptRef = useRef(0)
  const clarificationRef = useRef(false)
  const turnIdsRef = useRef(new Map<string, string>())
  const syncedConversationItemsRef = useRef(new Set<string>())
  const userCaptionsRef = useRef<ConversationCaption[]>([])
  // Customer transcript items a turn has already been sent for. One turn runs at a time, so
  // whatever is not in here and has finished transcribing is exactly the next turn.
  const consumedTranscriptItemsRef = useRef(new Set<string>())
  // Strings the last turn's plan said must be spoken word for word. Observed only: a miss
  // puts the full text on screen and never sends the model back to re-read anything.
  const pendingVerbatimRef = useRef<string[]>([])
  const verbatimBaselineRef = useRef(new Set<string>())
  // The single arbiter of anything the application makes the model say. Created per
  // connection, alongside the realtime session it speaks through.
  const speechFloorRef = useRef<SpeechFloor | null>(null)
  // The persona the live connection was minted with. Every response repeats it in full (see
  // `turnInstructions`), including the ones requested from outside `connectVoice`.
  const voicePersonaRef = useRef<string | null>(null)
  const confirmationPromisesRef = useRef(
    new Map<string, { promise: Promise<FlowResult>; revision: number }>(),
  )
  const identificationPromiseRef = useRef<Promise<FlowResult> | null>(null)
  const reconciliationPromiseRef = useRef<{
    sessionId: string
    revision: number
    promise: Promise<KioskSessionStatus>
  } | null>(null)
  const completionIntervalRef = useRef<number | null>(null)
  const terminalAudioTimeoutRef = useRef<number | null>(null)
  const followUpTimeoutRef = useRef<number | null>(null)
  const followUpPendingRef = useRef(false)
  // The stages of the turn being answered, reported when its first audio plays.
  const turnTimingRef = useRef<TurnTiming | null>(null)
  const conversationClosePendingRef = useRef(false)

  const updateState = useCallback((updater: (current: KioskState) => KioskState) => {
    const next = updater(stateRef.current)
    businessRevisionRef.current += 1
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
    if (followUpTimeoutRef.current !== null) {
      window.clearTimeout(followUpTimeoutRef.current)
      followUpTimeoutRef.current = null
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
        // The connection may already have been closed by the transport.
      }
    }
    pendingVerbatimRef.current = []
    verbatimBaselineRef.current.clear()
    speechFloorRef.current?.reset()
    speechFloorRef.current = null
    voicePersonaRef.current = null
    turnTimingRef.current = null
    conversationClosePendingRef.current = false
    // A pause belongs to the connection it was made on. Whatever replaces this one -- a
    // retry, a new session, the text mode -- starts out listening.
    listeningPausedRef.current = false
    setListeningPausedState(false)
  }, [])

  const clearFlowTracking = useCallback(() => {
    clarificationRef.current = false
    pendingVerbatimRef.current = []
    verbatimBaselineRef.current.clear()
    turnIdsRef.current.clear()
    syncedConversationItemsRef.current.clear()
    userCaptionsRef.current = []
    consumedTranscriptItemsRef.current.clear()
    confirmationPromisesRef.current.clear()
    identificationPromiseRef.current = null
    reconciliationPromiseRef.current = null
    followUpPendingRef.current = false
    conversationClosePendingRef.current = false
  }, [])

  const reset = useCallback(() => {
    clearTimers()
    disposeRealtime()
    clearFlowTracking()
    setCaptions([])
    setVoiceError(null)
    setVoiceState("idle")
    setCompletionSeconds(null)
    updateState(() => emptyState)
  }, [clearFlowTracking, clearTimers, disposeRealtime, updateState])

  const closeSessionNow = useCallback(() => {
    if (completionIntervalRef.current !== null) return

    if (terminalAudioTimeoutRef.current !== null) {
      window.clearTimeout(terminalAudioTimeoutRef.current)
      terminalAudioTimeoutRef.current = null
    }
    if (followUpTimeoutRef.current !== null) {
      window.clearTimeout(followUpTimeoutRef.current)
      followUpTimeoutRef.current = null
    }
    try {
      realtimeRef.current?.mute(true)
    } catch {
      // The subsequent close guarantees the microphone ends up released.
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
    }, 1_000)
  }, [disposeRealtime, reset])

  // Tearing the transport down cuts off whatever is being said, so give the model the end
  // of its sentence first. `armTerminalCompletion`'s timeout is the hard ceiling, so a
  // floor that never frees still cannot hold the kiosk open.
  const startCompletionCountdown = useCallback(() => {
    if (completionIntervalRef.current !== null) return
    const floor = speechFloorRef.current
    if (floor?.busy) {
      floor.whenFree(closeSessionNow)
      return
    }
    closeSessionNow()
  }, [closeSessionNow])

  const cancelFollowUpWindow = useCallback(() => {
    if (followUpTimeoutRef.current !== null) {
      window.clearTimeout(followUpTimeoutRef.current)
      followUpTimeoutRef.current = null
    }
  }, [])

  // An automatic answer keeps the session open so the customer can ask something else, but a
  // kiosk that waits forever is a kiosk nobody else can use. Give the follow-up a window; if
  // nothing comes, finish the session the usual way.
  const armFollowUpWindow = useCallback(() => {
    if (followUpTimeoutRef.current !== null) {
      window.clearTimeout(followUpTimeoutRef.current)
    }
    const seconds = listeningPausedRef.current
      ? PAUSED_FOLLOW_UP_INACTIVITY_SECONDS
      : (config?.kiosk_follow_up_inactivity_seconds ?? DEFAULT_FOLLOW_UP_INACTIVITY_SECONDS)
    followUpTimeoutRef.current = window.setTimeout(startCompletionCountdown, seconds * 1_000)
  }, [config?.kiosk_follow_up_inactivity_seconds, startCompletionCountdown])

  const noteUserActivity = useCallback(() => {
    if (!followUpPendingRef.current) return
    armFollowUpWindow()
  }, [armFollowUpWindow])

  // The hard ceiling, and the reason `startCompletionCountdown` can afford to wait for the
  // model: this one closes the session whether or not anything is still being said.
  const armTerminalCompletion = useCallback(() => {
    if (terminalAudioTimeoutRef.current !== null) return
    terminalAudioTimeoutRef.current = window.setTimeout(
      closeSessionNow,
      TERMINAL_AUDIO_TIMEOUT_MS,
    )
  }, [closeSessionNow])

  const restoreConversationHistory = useCallback(
    async (activeSession: KioskSession) => {
      const history = await kioskSessionRequest<ConversationHistory>(
        activeSession,
        "/conversation/messages",
      )
      if (stateRef.current.session?.session_id !== activeSession.session_id) return

      const restored = captionsFromStoredConversation(history.messages)
      restored.forEach((caption) => {
        syncedConversationItemsRef.current.add(caption.id)
        if (caption.role === "user") consumedTranscriptItemsRef.current.add(caption.id)
      })
      setCaptions((current) => {
        const merged = mergeConversationCaptions(restored, current)
        userCaptionsRef.current = merged
        return merged
      })
    },
    [],
  )

  const reconcileSession = useCallback(
    async (activeSession: KioskSession): Promise<KioskSessionStatus | null> => {
      const existing = reconciliationPromiseRef.current
      let promise: Promise<KioskSessionStatus>
      let requestRevision: number
      if (existing?.sessionId === activeSession.session_id) {
        promise = existing.promise
        requestRevision = existing.revision
      } else {
        requestRevision = businessRevisionRef.current
        promise = kioskSessionRequest<KioskSessionStatus>(activeSession, "")
        reconciliationPromiseRef.current = {
          sessionId: activeSession.session_id,
          revision: requestRevision,
          promise,
        }
      }

      try {
        const [snapshot] = await Promise.all([
          promise,
          restoreConversationHistory(activeSession),
        ])
        if (stateRef.current.session?.session_id !== activeSession.session_id) {
          return snapshot
        }
        if (businessRevisionRef.current !== requestRevision) return snapshot

        const analysis = snapshot.analysis ?? null
        const isClarification = analysis?.next_action === "CLARIFY"
        clarificationRef.current = isClarification
        updateState((stored) => {
          const transientCapture =
            !snapshot.result &&
            stored.result?.next_action === "CAPTURE" &&
            stored.result.status === snapshot.status
              ? stored.result
              : null
          return {
            ...stored,
            session: stored.session
              ? { ...stored.session, status: snapshot.status }
              : stored.session,
            analysis,
            result: snapshot.result ?? transientCapture,
            isClarification,
          }
        })
        followUpPendingRef.current =
          Boolean(snapshot.result?.conversation_can_continue) ||
          declineCanContinue(analysis)
        return snapshot
      } catch (reason) {
        if (
          stateRef.current.session?.session_id === activeSession.session_id &&
          reason instanceof ApiError &&
          reason.code === "SESSION_EXPIRED"
        ) {
          reset()
          return null
        }
        throw reason
      } finally {
        if (reconciliationPromiseRef.current?.promise === promise) {
          reconciliationPromiseRef.current = null
        }
      }
    },
    [reset, restoreConversationHistory, updateState],
  )

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      void (async () => {
        const raw = [STORAGE_KEY, ...LEGACY_STORAGE_KEYS]
          .map((key) => sessionStorage.getItem(key))
          .find((value): value is string => value !== null)
        for (const key of LEGACY_STORAGE_KEYS) sessionStorage.removeItem(key)
        if (raw) {
          let restored: KioskState | null = null
          try {
            restored = JSON.parse(raw) as KioskState
            if (
              restored.session &&
              new Date(restored.session.expires_at) > new Date()
            ) {
              restored.interactionMode =
                restored.interactionMode === "text" ? "text" : "voice"
              stateRef.current = restored
              clarificationRef.current = restored.isClarification
              setState(restored)
            } else {
              restored = null
              sessionStorage.removeItem(STORAGE_KEY)
            }
          } catch {
            sessionStorage.removeItem(STORAGE_KEY)
          }
          if (restored?.session) {
            try {
              await reconcileSession(restored.session)
            } catch (reason) {
              setVoiceError(errorMessage(reason))
            }
          }
        }
        if (!cancelled) setHydrated(true)
      })()
    })
    return () => {
      cancelled = true
    }
  }, [reconcileSession])

  useEffect(() => {
    if (!hydrated) return
    if (state.session) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    else sessionStorage.removeItem(STORAGE_KEY)
  }, [hydrated, state])

  useEffect(() => {
    if (!hydrated) return
    const target = kioskRouteForState(state)
    if (pathname !== target) router.replace(target)
  }, [hydrated, pathname, router, state])

  // Applied at the moment a result is stored, not a render later. Closing the credential
  // window through an effect meant the microphone stayed open across the tick in which the
  // kiosk was already saying "escribe tu CI" -- long enough for its own speaker to reach the
  // voice-activity detector. The effect below stays as the reconciliation backstop for state
  // that arrives from anywhere other than a business call.
  const applyMicrophonePolicy = useCallback(() => {
    const realtime = realtimeRef.current
    if (realtime?.transport.status !== "connected") return
    // The customer's pause only ever closes. It cannot open a microphone the business state
    // keeps shut, and no business state change reopens one the customer paused.
    const open = microphoneShouldBeOpen(stateRef.current) && !listeningPausedRef.current
    try {
      if (open) {
        // This used to only ever close. A rejected summary sends the session back to
        // CAPTURE, which is an open-mic state, but the mute applied while the credential
        // window was open stayed on -- and the person talked to a kiosk that was no longer
        // listening until they reconnected.
        if (!realtime.muted) return
        realtime.mute(false)
        queueMicrotask(() => setVoiceState("listening"))
        return
      }
      if (realtime.muted) return
      realtime.mute(true)
      queueMicrotask(() => setVoiceState("muted"))
    } catch {
      // Navigation and business state do not depend on the voice transport.
    }
  }, [])

  // Pausing does not interrupt the kiosk: whatever it is saying finishes, it just stops
  // hearing the customer until they resume.
  const setListeningPaused = useCallback(
    (paused: boolean) => {
      if (realtimeRef.current?.transport.status !== "connected") return
      if (!microphoneShouldBeOpen(stateRef.current)) return
      if (listeningPausedRef.current === paused) return
      listeningPausedRef.current = paused
      setListeningPausedState(paused)
      applyMicrophonePolicy()
      // A follow-up window already running was sized for the previous mode. One that has not
      // started yet picks the right size when the kiosk stops speaking.
      if (followUpTimeoutRef.current !== null) armFollowUpWindow()
    },
    [applyMicrophonePolicy, armFollowUpWindow],
  )

  useEffect(() => {
    applyMicrophonePolicy()
    const handedOff = state.result ? isTerminalFlowResult(state.result) : false
    const declined = isTerminalDecline(state.analysis)
    if (handedOff || declined) armTerminalCompletion()
  }, [applyMicrophonePolicy, armTerminalCompletion, state.result, state.analysis])

  useEffect(() => {
    if (
      hydrated &&
      state.result?.next_action === "COMPLETE" &&
      isTerminalFlowResult(state.result) &&
      completionSeconds === null &&
      realtimeRef.current?.transport.status !== "connected"
    ) {
      // Reached with no voice transport at all (text-only kiosk, or a dropped connection),
      // so there is no follow-up to wait for either way -- automatic or not.
      startCompletionCountdown()
    }
  }, [
    completionSeconds,
    hydrated,
    startCompletionCountdown,
    state.result,
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
      clearFlowTracking()
      setCaptions([])
      setVoiceError(null)
      setVoiceState("idle")
      setCompletionSeconds(null)
      updateState(() => emptyState)
      const session = await createKioskSession(preferentialAttention)
      updateState(() => ({ ...emptyState, session }))
    },
    [clearFlowTracking, clearTimers, disposeRealtime, updateState],
  )

  const handleExpiredSession = useCallback(() => {
    reset()
  }, [reset])

  // Everything the model has already said is baseline: a check must measure only what comes
  // out after this turn's outcome, not the whole conversation so far.
  const rememberVerbatim = useCallback((plan: SpeechPlan | undefined) => {
    pendingVerbatimRef.current = plan?.verbatim ?? []
    verbatimBaselineRef.current = new Set(
      userCaptionsRef.current
        .filter((caption) => caption.role === "assistant")
        .map((caption) => caption.id),
    )
  }, [])

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
    const isBusinessSessionCurrent = () =>
      stateRef.current.session?.session_id === activeSession.session_id

    const connection = (async () => {
      setVoiceError(null)

      try {
        const reconciled = await reconcileSession(activeSession)
        if (!isActiveAttempt() || !reconciled) return
        const completed = stateRef.current.result
        if (completed && isTerminalFlowResult(completed)) {
          setVoiceState("idle")
          return
        }

        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Este navegador no permite capturar audio")
        }
        setVoiceState("connecting")

        const secret = await kioskSessionRequest<RealtimeSecret>(
          activeSession,
          "/realtime-token",
          { method: "POST" },
        )
        if (attemptId !== connectionAttemptRef.current) return

        // The persona, model, voice and audio input configuration all come from the secret
        // the backend minted. There is no fallback on purpose: a missing field means the
        // backend changed shape, and silently connecting with SDK defaults would swap the
        // kiosk's persona, model and transcription model for something nobody chose.
        const {
          model,
          instructions,
          voice,
          audio_input: audioInput,
        } = secret.session ?? {}
        if (
          !model ||
          !instructions ||
          !voice ||
          !audioInput?.transcription?.model ||
          !audioInput.turn_detection
        ) {
          throw new Error("El canal de voz no llegó configurado; inténtalo nuevamente")
        }

        const [{ RealtimeSession: RealtimeSessionClass }, { createKioskRealtimeAgent }] =
          await Promise.all([
            import("@openai/agents/realtime"),
            import("@/lib/kiosk-realtime-agent"),
          ])
        if (attemptId !== connectionAttemptRef.current) return

        let agentRequirementId =
          stateRef.current.analysis?.requirement_id ??
          stateRef.current.result?.requirement_id ??
          null
        // The requirement a confirmation would land on. Business state first, because it is
        // the reconciled one; the agent's own last answer only covers the window before the
        // state has caught up.
        const pendingRequirementId = (): string | null =>
          stateRef.current.analysis?.requirement_id ??
          stateRef.current.result?.requirement_id ??
          agentRequirementId
        // Resolves to `null` when the answer came back after the conversation had moved on.
        // The caller turns that into a `superseded` result: the response is real, it is kept
        // for reconciliation, and it must not reach the speaker. Returning it unchanged --
        // which is what this used to do -- meant the client refused to *show* an obsolete
        // answer and read it out anyway.
        const analyzeRequirement = async (
          transcript: string,
          callId?: string,
          signal?: AbortSignal,
        ): Promise<TurnAnalysis | null> => {
          const key = callId ?? crypto.randomUUID()
          const requestRevision = businessRevisionRef.current
          const startingRequirementId =
            stateRef.current.analysis?.requirement_id ?? null
          let turnId = turnIdsRef.current.get(key)
          if (!turnId) {
            turnId = crypto.randomUUID()
            turnIdsRef.current.set(key, turnId)
          }

          try {
            cancelFollowUpWindow()
            followUpPendingRef.current = false
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
                signal,
              },
            )
            if (!isBusinessSessionCurrent()) return null
            // A confident GENERAL request resolves on this same turn -- no confirmation
            // round-trip -- and next_action is COMPLETE with the answer embedded in
            // `result`. Store it exactly like confirmRequirement / submitIdentification
            // store a completed flow, so routing and the mic policy (both keyed off
            // state.result) apply unchanged.
            if (response.next_action === "COMPLETE" && response.result) {
              const completedFlow = response.result
              if (
                !shouldApplyFlowResponse(
                  stateRef.current,
                  completedFlow,
                  startingRequirementId ?? completedFlow.requirement_id,
                  businessRevisionRef.current !== requestRevision,
                )
              ) {
                return null
              }
              agentRequirementId = response.requirement_id
              rememberVerbatim(analysisSpeechPlan(response))
              setVoiceError(null)
              clarificationRef.current = false
              updateState((stored) => ({
                ...stored,
                session: stored.session
                  ? { ...stored.session, status: completedFlow.status }
                  : stored.session,
                analysis: null,
                result: completedFlow,
                isClarification: false,
              }))
              followUpPendingRef.current = completedFlow.conversation_can_continue
              applyMicrophonePolicy()
              return response
            }
            if (
              !shouldApplyAnalysisResponse(
                stateRef.current,
                response,
                startingRequirementId,
                businessRevisionRef.current !== requestRevision,
              )
            ) {
              return null
            }
            agentRequirementId = response.requirement_id
            rememberVerbatim(analysisSpeechPlan(response))
            setVoiceError(null)
            const isClarification = response.next_action === "CLARIFY"
            clarificationRef.current = isClarification
            updateState((stored) => ({
              ...stored,
              session: stored.session
                ? { ...stored.session, status: response.status }
                : stored.session,
              analysis: response,
              result: null,
              isClarification,
            }))
            // A decline the kiosk recovers from waits for the next request like an automatic
            // answer does, and frees the kiosk the same way if none comes.
            followUpPendingRef.current = declineCanContinue(response)
            applyMicrophonePolicy()
            return response
          } catch (reason) {
            if (!isBusinessSessionCurrent()) {
              throw reason
            }
            const currentState = stateRef.current
            const requestWasSuperseded =
              businessRevisionRef.current !== requestRevision &&
              (currentState.result !== null ||
                (currentState.analysis !== null &&
                  currentState.analysis.requirement_id !==
                    startingRequirementId))
            if (requestWasSuperseded) {
              throw reason
            } else if (
              reason instanceof ApiError &&
              reason.code === "SESSION_EXPIRED"
            ) {
              handleExpiredSession()
            } else if (!isSessionStateConflict(reason) && !isSessionExhausted(reason)) {
              // A state conflict is this client disagreeing with the session about where
              // the conversation is -- `POST /turns` is refused for the whole time the CI
              // field is open. Painting the reconnect banner over the identification
              // screen for that was how a working kiosk looked broken.
              setVoiceError(errorMessage(reason))
            }
            throw reason
          }
        }
        // `null` for the same reason as `analyzeRequirement`: a confirmation the customer has
        // already overtaken must not be narrated.
        const confirmRequirement = async (
          confirmed: boolean | null,
          transcript?: string,
          signal?: AbortSignal,
        ): Promise<FlowResult | null> => {
          const requirementId = pendingRequirementId()
          if (!requirementId) {
            throw new Error("No existe un requerimiento pendiente de confirmación")
          }
          const requestKey = `${activeSession.session_id}:${requirementId}:${confirmed}`
          let requestEntry = confirmationPromisesRef.current.get(requestKey)
          if (!requestEntry) {
            requestEntry = {
              revision: businessRevisionRef.current,
              promise: kioskSessionRequest<FlowResult>(
                activeSession,
                "/confirmation",
                {
                  method: "POST",
                  body: JSON.stringify({
                    requirement_id: requirementId,
                    confirmed,
                    // The backend decides what the reply meant; this is only what the person
                    // actually said. Sending the words is what lets "sí, pero primero quiero
                    // consultar" stop being a yes.
                    transcript: transcript ?? null,
                  }),
                  signal,
                },
              ),
            }
            confirmationPromisesRef.current.set(requestKey, requestEntry)
          }

          try {
            const response = await requestEntry.promise
            if (!isBusinessSessionCurrent()) return null
            if (
              !shouldApplyFlowResponse(
                stateRef.current,
                response,
                requirementId,
                businessRevisionRef.current !== requestEntry.revision,
              )
            ) {
              return null
            }
            rememberVerbatim(response.speech_plan)
            setVoiceError(null)
            clarificationRef.current = false
            updateState((stored) => ({
              ...stored,
              session: stored.session
                ? { ...stored.session, status: response.status }
                : stored.session,
              analysis: null,
              result: response,
              isClarification: false,
            }))
            followUpPendingRef.current = Boolean(
              response.conversation_can_continue,
            )
            applyMicrophonePolicy()
            return response
          } catch (reason) {
            if (
              confirmationPromisesRef.current.get(requestKey) === requestEntry
            ) {
              confirmationPromisesRef.current.delete(requestKey)
            }
            if (!isBusinessSessionCurrent()) {
              throw reason
            }
            const currentState = stateRef.current
            const requestWasSuperseded =
              businessRevisionRef.current !== requestEntry.revision &&
              (currentState.result !== null ||
                (currentState.analysis !== null &&
                  currentState.analysis.requirement_id !== requirementId))
            if (requestWasSuperseded) {
              throw reason
            } else if (
              reason instanceof ApiError &&
              reason.code === "SESSION_EXPIRED"
            ) {
              handleExpiredSession()
            } else if (!isSessionStateConflict(reason) && !isSessionExhausted(reason)) {
              setVoiceError(errorMessage(reason))
            }
            throw reason
          }
        }
        // Every state the session can be in needs an answer here. There used to be two
        // branches -- confirmation, and everything else goes to `/turns` -- so a turn
        // spoken while the credential window was open fell through to an endpoint the backend
        // refuses in that state, and the 409 reached the customer as "no pude consultar el
        // sistema, inténtalo otra vez". The kiosk knows perfectly well what is happening;
        // it just had nowhere to say so.
        const routeSpokenTurn = async (
          transcript: string,
          callId?: string,
          signal?: AbortSignal,
        ): Promise<KioskTurnProcessingResult> => {
          if (followUpPendingRef.current && isConversationClose(transcript)) {
            cancelFollowUpWindow()
            followUpPendingRef.current = false
            conversationClosePendingRef.current = true
            return { kind: "close" }
          }

          const { analysis, result } = stateRef.current
          if (result?.next_action === "IDENTIFY") return { kind: "awaiting_identification" }
          if (result && isTerminalFlowResult(result)) return { kind: "settled" }
          if (isTerminalDecline(analysis)) return { kind: "settled" }

          // A CONFIRM result means the backend read the last reply as a question or as
          // unreadable: the session is still AWAITING_CONFIRMATION, so the next reply
          // belongs to `/confirmation` too. Sending it to `/turns` in that state gets the
          // same summary handed back, which is the answer the person was questioning.
          if (analysis?.next_action === "CONFIRM" || result?.next_action === "CONFIRM") {
            // The regex is a shortcut for unmistakable replies, not the decision. "Sí, pero
            // quiero consultar primero" and "Claro, ¿qué entendiste?" are not confirmations,
            // and no amount of cue-matching in a browser settles that -- the backend reads
            // the words and says what they meant.
            const response = await confirmRequirement(
              explicitConfirmation(transcript),
              transcript,
              signal,
            )
            if (!response) return { kind: "superseded" }
            // A rejection that named what the person wanted instead. They said it once
            // already; putting it through the normal turn path is what keeps them from
            // having to say it again, and it is their own words as the backend read them --
            // classified, floored and state-guarded like any other turn.
            const correction = correctedRequest(response)
            if (correction) {
              const corrected = await analyzeRequirement(correction, undefined, signal)
              if (!corrected) return { kind: "superseded" }
              return { kind: "analysis", response: corrected }
            }
            return { kind: "flow", response }
          }

          const analysisResponse = await analyzeRequirement(transcript, callId, signal)
          if (!analysisResponse) return { kind: "superseded" }
          return { kind: "analysis", response: analysisResponse }
        }

        const processSpokenTurn = async (
          transcript: string,
          turnKey: string,
          signal: AbortSignal,
        ): Promise<KioskTurnProcessingResult> => {
          try {
            return await routeSpokenTurn(transcript, turnKey, signal)
          } catch (reason) {
            // The backend and this client disagreed about where the conversation is.
            // Reconcile and say nothing: the customer did nothing wrong and the bank is not
            // down, so an apology here would be a lie about both. Awaited, so the caller can
            // route the same words again against the state the session is really in.
            if (isSessionStateConflict(reason)) {
              await reconcileSession(activeSession).catch(() => {
                // A failed reconciliation surfaces through its own paths.
              })
              return { kind: "noop" }
            }
            if (isSessionExhausted(reason)) {
              conversationClosePendingRef.current = true
              return { kind: "close" }
            }
            throw reason
          }
        }

        const agent = createKioskRealtimeAgent({ instructions, voice })
        voicePersonaRef.current = instructions

        // The application owns the turn, so it has to know what the session is doing: whether
        // the opening line is still going out, whether the customer is mid-sentence, whether a
        // turn is already with the bank. Per connection on purpose -- a reconnect starts over.
        let openingDone = false
        let interruptionsEnabled = false
        let customerSpeaking = false
        let turnInFlight = false
        let lastSpeechStoppedAt: number | null = null
        let fragmentTimer: number | null = null
        // The fragment that already waited its moment, so it is sent instead of held again.
        let releasedFragment: string | null = null

        const realtime = new RealtimeSessionClass(agent, {
          model,
          historyStoreAudio: false,
          tracingDisabled: true,
          config: realtimeVoiceSessionConfig(audioInput, voice, { interruptResponse: false }),
        })
        realtimeRef.current = realtime
        const isCurrentRealtime = () =>
          isActiveAttempt() && realtimeRef.current === realtime

        const speechFloor = new SpeechFloor({
          speak: (text) => {
            try {
              // Through `sendEvent`, so the SDK's own sequencer still holds a request that
              // arrives while a response is active instead of having it rejected.
              realtime.transport.sendEvent({
                type: "response.create",
                response: { instructions: text, tool_choice: "none" },
              })
            } catch (reason) {
              // The floor drops the request and moves on; the customer still needs to be
              // told that the rest of this is on screen rather than left waiting for a
              // voice that is not coming.
              setVoiceError(
                "No fue posible continuar la conversación por voz; el resultado " +
                  "permanece en pantalla.",
              )
              startCompletionCountdown()
              throw reason
            }
          },
          interrupt: () => realtime.interrupt(),
        })
        speechFloorRef.current = speechFloor

        const enableInterruptions = () => {
          if (interruptionsEnabled) return
          interruptionsEnabled = true
          try {
            realtime.transport.updateSessionConfig(
              realtimeVoiceSessionConfig(audioInput, voice, { interruptResponse: true }),
            )
          } catch {
            // The transport is gone; the next connection mints its own configuration.
          }
        }

        const settleVoiceState = () => {
          if (turnInFlight) return
          setVoiceState(realtime.muted ? "muted" : "listening")
        }

        const dropPendingVerbatim = () => {
          pendingVerbatimRef.current = []
          verbatimBaselineRef.current.clear()
        }

        const clearFragmentHold = () => {
          if (fragmentTimer === null) return
          window.clearTimeout(fragmentTimer)
          fragmentTimer = null
        }

        // What became of the old controlled-speech machine: an observation, not a
        // correction. When a turn's plan carried strings that must survive word for word,
        // check the model said them -- and if it did not, leave the full text on screen and
        // say so once. It used to push a "say this word for word" message back into the
        // conversation instead, which starts a whole new response; with "Ventanilla 3" and
        // ticket numbers in `verbatim`, a model that correctly said "ventanilla tres" was
        // sent back to recite a fragment, and that fragment is what a customer heard
        // trailing their ticket number. `missingVerbatim` now also ignores anything with a
        // digit, because speech never renders one as written.
        const checkVerbatim = () => {
          const required = pendingVerbatimRef.current
          if (required.length === 0) return
          const spoken = userCaptionsRef.current
            .filter(
              (caption) =>
                caption.role === "assistant" &&
                caption.completed &&
                !verbatimBaselineRef.current.has(caption.id),
            )
            .map((caption) => caption.text)
            .join(" ")
          // Nothing transcribed yet for this turn. Saying it fell short would be a guess.
          if (!spoken) return

          pendingVerbatimRef.current = []
          if (missingVerbatim(spoken, required).length === 0) return
          setVoiceError(
            "No pude reproducir toda la respuesta; el detalle completo está en pantalla.",
          )
        }

        // Sends the next turn to the bank once there is one to send. Called whenever any of
        // its conditions may have changed: a transcription landed, the customer stopped
        // talking, the opening line finished, the previous turn came back. A turn spoken while
        // another one is with the bank is not lost -- it is still unspent when that one
        // returns, and it goes next, joined with anything else said in the meantime.
        const maybeRunTurn = () => {
          if (!isCurrentRealtime() || !openingDone || turnInFlight || customerSpeaking) return
          const selection = selectAuthoritativeTranscript(
            userCaptionsRef.current,
            consumedTranscriptItemsRef.current,
          )
          if (!selection) return
          const { analysis, result } = stateRef.current
          const awaitingAnswer =
            analysis?.next_action === "CONFIRM" || result?.next_action === "CONFIRM"
          const key = selection.itemIds.join("|")
          if (!awaitingAnswer && isSpeechFragment(selection.text) && releasedFragment !== key) {
            if (fragmentTimer === null) {
              fragmentTimer = window.setTimeout(() => {
                fragmentTimer = null
                releasedFragment = key
                maybeRunTurn()
              }, FRAGMENT_HOLD_MS)
            }
            return
          }
          clearFragmentHold()
          void runSpokenTurn(selection)
        }

        const runSpokenTurn = async (selection: TranscriptSelection) => {
          turnInFlight = true
          const timing: TurnTiming = {
            speechStoppedAt: lastSpeechStoppedAt,
            transcriptAt: performance.now(),
            backendAt: null,
          }
          lastSpeechStoppedAt = null
          // A new turn. Any unchecked requirement from the preceding answer belongs to the
          // answer before it, not to this one. The microphone stays live: the customer must
          // be able to interrupt, correct or add something while the bank answers.
          dropPendingVerbatim()
          cancelFollowUpWindow()
          setVoiceState("thinking")

          const controller = new AbortController()
          const timeout = window.setTimeout(() => controller.abort(), TURN_TIMEOUT_MS)
          const filler = window.setTimeout(() => {
            speechFloor.request("filler", () =>
              turnInFlight && isCurrentRealtime() ? fillerInstructions(instructions) : null,
            )
          }, FILLER_DELAY_MS)
          const turnKey = crypto.randomUUID()
          let result: KioskTurnProcessingResult = { kind: "noop" }
          try {
            // A state disagreement has been reconciled by the time `noop` comes back, and
            // nobody has read these words yet: route them once more against the state the
            // session is really in, instead of leaving the person unanswered.
            for (let attempt = 0; attempt < 2 && result.kind === "noop"; attempt += 1) {
              result = await processSpokenTurn(selection.text, turnKey, controller.signal)
            }
          } catch {
            // Only a genuine outage reaches here, or the bank taking longer than
            // TURN_TIMEOUT_MS. The words are spent anyway: left unspent, they would be sent
            // again the instant this returned, against a bank that just failed, and the
            // apology already asks the person to say it again.
            result = { kind: "retry", guidance: OUTAGE_GUIDANCE }
          } finally {
            window.clearTimeout(timeout)
            window.clearTimeout(filler)
            selection.itemIds.forEach((itemId) => consumedTranscriptItemsRef.current.add(itemId))
            turnInFlight = false
          }
          if (!isCurrentRealtime()) return

          timing.backendAt = performance.now()
          turnTimingRef.current = timing
          // Re-derived when the floor frees, so an outcome the conversation has overtaken in
          // the meantime -- or one with nothing to say -- produces no response at all.
          speechFloor.request("turn", () =>
            isCurrentRealtime() ? turnInstructions(instructions, result) : null,
          )
          settleVoiceState()
          maybeRunTurn()
        }

        realtime.on("history_updated", (history) => {
          if (!isCurrentRealtime()) return
          const liveCaptions = captionsFromHistory(history)
          const nextCaptions = mergeConversationCaptions(
            userCaptionsRef.current,
            liveCaptions,
          )
          setCaptions(nextCaptions)
          userCaptionsRef.current = nextCaptions
          // A customer transcript landing here is what starts a turn.
          maybeRunTurn()
          const session = stateRef.current.session
          const pending = nextCaptions.filter(
            (caption) =>
              caption.completed && !syncedConversationItemsRef.current.has(caption.id),
          )
          if (pending.length === 0 || !session) return
          pending.forEach((caption) => syncedConversationItemsRef.current.add(caption.id))
          void kioskSessionRequest(session, "/conversation/messages", {
            method: "POST",
            body: JSON.stringify({
              messages: pending.map((caption) => ({
                item_id: caption.id,
                role: caption.role === "user" ? "CUSTOMER" : "ASSISTANT",
                text: caption.text,
              })),
            }),
          }).catch(() => {
            pending.forEach((caption) => syncedConversationItemsRef.current.delete(caption.id))
          })
        })
        realtime.on("audio_start", () => {
          if (!isCurrentRealtime()) return
          // The SDK event carries no response id; `output_audio_buffer.started` below does,
          // and that is the one the floor is told about. This only paints the UI.
          setVoiceState("speaking")
          const timing = turnTimingRef.current
          if (timing !== null) {
            turnTimingRef.current = null
            reportTurnLatency(timing, performance.now())
          }
        })
        realtime.on("audio_stopped", () => {
          if (!isCurrentRealtime()) return
          checkVerbatim()
          settleVoiceState()
        })
        realtime.on("transport_event", (event) => {
          if (!isCurrentRealtime()) return
          const responseId = realtimeResponseId(event)
          if (event.type === "response.created") {
            speechFloor.noteResponseStarted(responseId)
          } else if (event.type === "response.done") {
            speechFloor.noteResponseDone(responseId)
          } else if (event.type === "output_audio_buffer.started") {
            speechFloor.noteAudioStarted(responseId)
          } else if (
            event.type === "output_audio_buffer.stopped" ||
            event.type === "output_audio_buffer.cleared"
          ) {
            // Fires after playback actually finishes, later than `audio_stopped` -- by which
            // point the transcript of the turn has usually landed. The check is idempotent,
            // so running it at both moments only makes it more likely to see the text at all.
            speechFloor.noteAudioFinished(responseId)
            checkVerbatim()
            settleVoiceState()
            if (conversationClosePendingRef.current) {
              conversationClosePendingRef.current = false
              startCompletionCountdown()
            } else if (followUpPendingRef.current) {
              armFollowUpWindow()
            }
          } else if (event.type === "input_audio_buffer.speech_started") {
            customerSpeaking = true
            // More is coming: a held fragment waits for it instead of going out alone.
            clearFragmentHold()
            // The customer is talking, possibly over the kiosk. That is a supported way to
            // use it, not a failure: nothing is replayed, and a verbatim string the model
            // was cut off from saying is dropped rather than forced through a second time.
            // (`audio_interrupted` used to carry this too, but only the WebSocket transport
            // ever emits it and the browser runs on WebRTC.)
            dropPendingVerbatim()
            cancelFollowUpWindow()
            setVoiceState("listening")
            // A barge-in stops the kiosk's audio without necessarily reporting the buffer as
            // stopped, and a floor still believing it is speaking never frees. Not during the
            // opening line, though: interruptions are off then, so the audio is still playing.
            if (interruptionsEnabled) speechFloor.noteAudioFinished()
          } else if (event.type === "input_audio_buffer.speech_stopped") {
            customerSpeaking = false
            lastSpeechStoppedAt = performance.now()
            maybeRunTurn()
          }
        })
        realtime.on("error", ({ error }) => {
          if (!isCurrentRealtime()) return
          // Losing a race for the response slot is not a broken session. The transport
          // queues our `response.create` behind whatever is speaking and cancels on
          // barge-in, and both can come back as an `error` event the customer must never be
          // asked to reconnect over.
          if (isBenignRealtimeError(error)) return
          setVoiceError(errorMessage(error))
          setVoiceState("error")
        })
        realtime.transport.on("connection_change", (status) => {
          if (status === "disconnected" && realtimeRef.current === realtime) {
            setVoiceError("Se perdió la conexión de voz")
            void reconcileSession(activeSession).catch(() => {
              // The transport error is already visible and can be retried manually.
            })
            setVoiceState("error")
          }
        })

        await realtime.connect({ apiKey: secret.value })
        if (attemptId !== connectionAttemptRef.current) return

        // Reconnecting straight onto the identification screen: the credential window is
        // already open, so the microphone must not be. Muting only closes the input track --
        // the model can still say what it needs to below. The mic-policy effect cannot cover
        // this one: the state was already IDENTIFY before there was a transport to mute.
        if (stateRef.current.result?.next_action === "IDENTIFY") {
          realtime.mute(true)
          setVoiceState("muted")
        } else {
          setVoiceState("listening")
        }

        // The opening line: a greeting, or the state a reconnect is resuming into. Through
        // the arbiter, and re-derived when it is released, so a reconnection that lands while
        // the business state is still moving does not narrate a step the kiosk has already
        // passed. On 2026-10-14 the greeting came out *last*, behind two answers to the
        // people talking around the kiosk; nothing else is asked for until it has been heard.
        const resume = resumeContext(stateRef.current)
        if (resume) {
          speechFloor.request("resume", () => {
            const current = resumeContext(stateRef.current)
            return current ? situationInstructions(instructions, current) : null
          })
        } else {
          speechFloor.request("greeting", () => greetingInstructions(instructions))
        }
        // Whatever was said over the opening line was transcribed all the same, and goes out
        // as the first turn the moment it ends.
        speechFloor.whenFree(() => {
          if (!isCurrentRealtime()) return
          openingDone = true
          enableInterruptions()
          maybeRunTurn()
        })
      } catch (reason) {
        if (attemptId !== connectionAttemptRef.current) return
        disposeRealtime()
        if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
          handleExpiredSession()
          return
        }
        let failure = reason
        if (reason instanceof ApiError && reason.code === "INVALID_SESSION_STATE") {
          try {
            const snapshot = await reconcileSession(activeSession)
            if (snapshot) return
          } catch (reconciliationReason) {
            failure = reconciliationReason
          }
        }
        setVoiceError(errorMessage(failure))
        setVoiceState("error")
        throw failure
      }
    })()

    connectPromiseRef.current = connection
    try {
      await connection
    } finally {
      if (connectPromiseRef.current === connection) connectPromiseRef.current = null
    }
  }, [
    applyMicrophonePolicy,
    armFollowUpWindow,
    cancelFollowUpWindow,
    disposeRealtime,
    handleExpiredSession,
    reconcileSession,
    rememberVerbatim,
    startCompletionCountdown,
    updateState,
  ])

  const retryVoice = useCallback(async () => {
    disposeRealtime()
    setVoiceError(null)
    setVoiceState("idle")
    await connectVoice()
  }, [connectVoice, disposeRealtime])

  const selectInteractionMode = useCallback(
    (mode: "voice" | "text") => {
      if (mode === "text") {
        disposeRealtime()
        setVoiceError(null)
        setVoiceState("idle")
      }
      updateState((stored) => ({ ...stored, interactionMode: mode }))
    },
    [disposeRealtime, updateState],
  )

  const syncTextExchange = useCallback(
    (
      activeSession: KioskSession,
      customerText: string,
      assistantText: string,
    ) => {
      const messages = [
        {
          item_id: `text-customer-${crypto.randomUUID()}`,
          role: "CUSTOMER",
          text: customerText,
        },
        {
          item_id: `text-assistant-${crypto.randomUUID()}`,
          role: "ASSISTANT",
          text: assistantText,
        },
      ]
      void kioskSessionRequest(activeSession, "/conversation/messages", {
        method: "POST",
        body: JSON.stringify({ messages }),
      }).catch(() => {
        // The business flow was already confirmed; sync can be skipped without duplicating it.
      })
    },
    [],
  )

  const submitTextTurn = useCallback(
    async (transcript: string): Promise<TurnAnalysis> => {
      const activeSession = stateRef.current.session
      if (!activeSession) throw new Error("No existe una sesión activa")
      let response: TurnAnalysis
      try {
        cancelFollowUpWindow()
        followUpPendingRef.current = false
        response = await kioskSessionRequest<TurnAnalysis>(
          activeSession,
          "/turns",
          {
            method: "POST",
            body: JSON.stringify({
              turn_id: crypto.randomUUID(),
              transcript: transcript.trim(),
              is_clarification: clarificationRef.current,
            }),
          },
        )
      } catch (reason) {
        if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
          handleExpiredSession()
        }
        throw reason
      }
      if (stateRef.current.session?.session_id !== activeSession.session_id) {
        return response
      }
      // A confident GENERAL request resolves on this same turn -- see the matching branch
      // in connectVoice's analyzeRequirement callback for why this stores into `result`
      // (a real FlowResult) instead of `analysis`.
      if (response.next_action === "COMPLETE" && response.result) {
        const completed = response.result
        clarificationRef.current = false
        setVoiceError(null)
        updateState((stored) => ({
          ...stored,
          session: stored.session
            ? { ...stored.session, status: completed.status }
            : stored.session,
          analysis: null,
          result: completed,
          isClarification: false,
        }))
        followUpPendingRef.current = completed.conversation_can_continue
        if (completed.conversation_can_continue) armFollowUpWindow()
        syncTextExchange(activeSession, transcript.trim(), response.speech_text)
        return response
      }
      const isClarification = response.next_action === "CLARIFY"
      clarificationRef.current = isClarification
      setVoiceError(null)
      updateState((stored) => ({
        ...stored,
        session: stored.session
          ? { ...stored.session, status: response.status }
          : stored.session,
        analysis: response,
        result: null,
        isClarification,
      }))
      followUpPendingRef.current = declineCanContinue(response)
      if (followUpPendingRef.current) armFollowUpWindow()
      syncTextExchange(activeSession, transcript.trim(), response.speech_text)
      return response
    },
    [
      armFollowUpWindow,
      cancelFollowUpWindow,
      handleExpiredSession,
      syncTextExchange,
      updateState,
    ],
  )

  const confirmText = useCallback(
    async (confirmed: boolean): Promise<FlowResult> => {
      const activeSession = stateRef.current.session
      const requirementId = stateRef.current.analysis?.requirement_id
      if (!activeSession || !requirementId) {
        throw new Error("No existe un requerimiento pendiente de confirmación")
      }
      let response: FlowResult
      try {
        response = await kioskSessionRequest<FlowResult>(
          activeSession,
          "/confirmation",
          {
            method: "POST",
            body: JSON.stringify({
              requirement_id: requirementId,
              confirmed,
            }),
          },
        )
      } catch (reason) {
        if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
          handleExpiredSession()
        }
        throw reason
      }
      if (stateRef.current.session?.session_id !== activeSession.session_id) {
        return response
      }
      clarificationRef.current = false
      setVoiceError(null)
      updateState((stored) => ({
        ...stored,
        session: stored.session
          ? { ...stored.session, status: response.status }
          : stored.session,
        analysis: null,
        result: response,
        isClarification: false,
      }))
      followUpPendingRef.current = Boolean(response.conversation_can_continue)
      if (response.conversation_can_continue) armFollowUpWindow()
      syncTextExchange(
        activeSession,
        confirmed ? "Sí, confirmo." : "No, quiero corregir.",
        response.speech_text,
      )
      return response
    },
    [armFollowUpWindow, handleExpiredSession, syncTextExchange, updateState],
  )

  const submitIdentification = useCallback(
    async (identifier: string) => {
      const activeSession = stateRef.current.session
      if (!activeSession) throw new Error("No existe una sesión activa")

      if (identificationPromiseRef.current) {
        return identificationPromiseRef.current
      }

      // Silence first, HTTP second. Whatever is being said right now is "escribe tu CI en el
      // campo protegido", and the CI is in: that sentence became obsolete before this
      // request was even sent, and cutting it only after the round trip -- which creates the
      // ticket and assigns an executive -- is why a fast typist heard it run to completion.
      // The floor also arms the cancellation of a response that has not started yet, so an
      // instruction still in flight never reaches the speaker at all.
      speechFloorRef.current?.silenceNow()

      const request = kioskSessionRequest<FlowResult>(
        activeSession,
        "/identification",
        {
          method: "POST",
          body: JSON.stringify({ identifier: identifier.trim() }),
        },
      )
      identificationPromiseRef.current = request

      try {
        const completed = await request
        if (stateRef.current.session?.session_id !== activeSession.session_id) {
          return completed
        }
        updateState((stored) => ({
          ...stored,
          session: stored.session
              ? { ...stored.session, status: completed.status }
              : stored.session,
          analysis: null,
          result: completed,
          isClarification: false,
        }))
        followUpPendingRef.current = false
        applyMicrophonePolicy()

        // A finished identification is not a request still in flight. Leaving the promise
        // here meant a second submit -- with a different identity card -- silently returned
        // the first one's result instead of being rejected or re-run.
        identificationPromiseRef.current = null

        const realtime = realtimeRef.current
        const speechFloor = speechFloorRef.current
        const persona = voicePersonaRef.current
        if (realtime?.transport.status === "connected" && speechFloor && persona) {
          // The microphone stays closed. It used to be opened here "so the customer can
          // react", but this result is terminal and the mic-policy effect shut it again a
          // tick later anyway -- all that window ever did was give the kiosk's own speaker
          // a path back into the voice-activity detector.
          rememberVerbatim(completed.speech_plan)
          // The identity card is typed on a form, so this outcome never passed through
          // speech. It is spoken from the backend's own SpeechPlan, exactly like a spoken
          // turn's outcome: on 2026-09-01 a model told to "say how this ends" from memory
          // assured a customer who had just been given ticket 1 at Ventanilla 4 that the next
          // step "depended on internal confirmation". The instruction was already cancelled
          // before the request went out; this supersedes anything started in the meantime.
          speechFloor.preempt("identification_close", () =>
            turnInstructions(persona, { kind: "flow", response: completed }),
          )
        } else if (stateRef.current.interactionMode === "voice") {
          setVoiceError(
            "La conexión de voz se cerró; el resultado permanece disponible en pantalla.",
          )
          startCompletionCountdown()
        } else {
          startCompletionCountdown()
        }
        return completed
      } catch (reason) {
        if (identificationPromiseRef.current === request) {
          identificationPromiseRef.current = null
        }
        // The identification did not happen, so the standing suppression has nothing left
        // to protect -- and the kiosk may well need to say what went wrong.
        speechFloorRef.current?.allowNextResponse()
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
      applyMicrophonePolicy,
      handleExpiredSession,
      rememberVerbatim,
      startCompletionCountdown,
      updateState,
    ],
  )

  const listeningControlAvailable =
    microphoneShouldBeOpen(state) &&
    (voiceState === "listening" ||
      voiceState === "thinking" ||
      voiceState === "speaking" ||
      voiceState === "muted")

  const value = useMemo<KioskContextValue>(
    () => ({
      ...state,
      hydrated,
      voiceState,
      voiceError,
      listeningPaused,
      listeningControlAvailable,
      setListeningPaused,
      captions,
      completionSeconds,
      beginSession,
      connectVoice,
      retryVoice,
      selectInteractionMode,
      noteUserActivity,
      submitTextTurn,
      confirmText,
      submitIdentification,
      reset,
    }),
    [
      beginSession,
      captions,
      completionSeconds,
      connectVoice,
      hydrated,
      listeningControlAvailable,
      listeningPaused,
      reset,
      retryVoice,
      selectInteractionMode,
      setListeningPaused,
      noteUserActivity,
      state,
      submitTextTurn,
      confirmText,
      submitIdentification,
      voiceError,
      voiceState,
    ],
  )

  return <KioskContext.Provider value={value}>{children}</KioskContext.Provider>
}

export function useKiosk(): KioskContextValue {
  const value = useContext(KioskContext)
  if (!value) throw new Error("useKiosk requires KioskProvider")
  return value
}
