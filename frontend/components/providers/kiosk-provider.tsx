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
  analysisTransitionKey,
  businessTransitionKey,
  canReplayControlledSpeech,
  captionsFromHistory,
  controlledSpeechInstructions,
  controlledTransitionFromToolResult,
  flowTransitionKey,
  kioskRouteForState,
  requestControlledResponse,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  shouldReplayControlledTransition,
  TRANSITION_METADATA_KEY,
  type ControlledTransition,
  type ConversationCaption,
} from "@/lib/kiosk-realtime"
import type {
  FlowResult,
  KioskSession,
  KioskSessionStatus,
  TurnAnalysis,
} from "@/lib/types"

const STORAGE_KEY = "orquestacion_kiosk_flow_v4"
const LEGACY_STORAGE_KEYS = [
  "orquestacion_kiosk_flow_v1",
  "orquestacion_kiosk_flow_v2",
  "orquestacion_kiosk_flow_v3",
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

interface TransitionRequest {
  transition: ControlledTransition
  revision: number
}

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
  captions: ConversationCaption[]
  completionSeconds: number | null
  beginSession: (preferentialAttention: boolean) => Promise<void>
  connectVoice: () => Promise<void>
  retryVoice: () => Promise<void>
  selectInteractionMode: (mode: "voice" | "text") => void
  submitTextTurn: (transcript: string) => Promise<TurnAnalysis>
  confirmText: (confirmed: boolean) => Promise<FlowResult>
  submitIdentification: (identifier: string) => Promise<FlowResult>
  reset: () => void
}

const KioskContext = createContext<KioskContextValue | null>(null)

function toolCallKey(toolCall: unknown, fallback: string): string {
  if (toolCall && typeof toolCall === "object") {
    if ("callId" in toolCall && typeof toolCall.callId === "string") {
      return toolCall.callId
    }
    if ("id" in toolCall && typeof toolCall.id === "string") {
      return toolCall.id
    }
  }
  return fallback
}

export function KioskProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [state, setState] = useState<KioskState>(emptyState)
  const [hydrated, setHydrated] = useState(false)
  const [voiceState, setVoiceState] = useState<VoiceState>("idle")
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [captions, setCaptions] = useState<ConversationCaption[]>([])
  const [completionSeconds, setCompletionSeconds] = useState<number | null>(null)

  const stateRef = useRef(state)
  const businessRevisionRef = useRef(0)
  const realtimeRef = useRef<RealtimeSession | null>(null)
  const connectPromiseRef = useRef<Promise<void> | null>(null)
  const connectionAttemptRef = useRef(0)
  const clarificationRef = useRef(false)
  const terminalTransitionKeyRef = useRef<string | null>(null)
  const activeTransitionKeyRef = useRef<string | null>(null)
  const audioDoneTransitionKeyRef = useRef<string | null>(null)
  const responseTransitionsRef = useRef(new Map<string, string>())
  const activeToolCallsRef = useRef(new Set<string>())
  const toolCallRevisionsRef = useRef(new Map<string, number>())
  const pendingToolTransitionRef = useRef<ControlledTransition | null>(null)
  const transitionRequestsRef = useRef(new Map<string, TransitionRequest>())
  const audioProducedTransitionsRef = useRef(new Set<string>())
  const replayAttemptsRef = useRef(new Map<string, number>())
  const interruptedReplayRef = useRef<TransitionRequest | null>(null)
  const postInterruptionResponseIdRef = useRef<string | null>(null)
  const inputSpeechActiveRef = useRef(false)
  const requestedTransitionsRef = useRef(new Set<string>())
  const completedTransitionsRef = useRef(new Set<string>())
  const turnIdsRef = useRef(new Map<string, string>())
  const syncedConversationItemsRef = useRef(new Set<string>())
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
  const interruptedReplayTimeoutRef = useRef<number | null>(null)

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
    if (interruptedReplayTimeoutRef.current !== null) {
      window.clearTimeout(interruptedReplayTimeoutRef.current)
      interruptedReplayTimeoutRef.current = null
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
    for (const transitionKey of requestedTransitionsRef.current) {
      if (!completedTransitionsRef.current.has(transitionKey)) {
        requestedTransitionsRef.current.delete(transitionKey)
      }
    }
    responseTransitionsRef.current.clear()
    activeToolCallsRef.current.clear()
    toolCallRevisionsRef.current.clear()
    pendingToolTransitionRef.current = null
    transitionRequestsRef.current.clear()
    audioProducedTransitionsRef.current.clear()
    replayAttemptsRef.current.clear()
    interruptedReplayRef.current = null
    postInterruptionResponseIdRef.current = null
    inputSpeechActiveRef.current = false
    if (interruptedReplayTimeoutRef.current !== null) {
      window.clearTimeout(interruptedReplayTimeoutRef.current)
      interruptedReplayTimeoutRef.current = null
    }
    activeTransitionKeyRef.current = null
    audioDoneTransitionKeyRef.current = null
  }, [])

  const clearFlowTracking = useCallback(() => {
    clarificationRef.current = false
    terminalTransitionKeyRef.current = null
    activeTransitionKeyRef.current = null
    audioDoneTransitionKeyRef.current = null
    requestedTransitionsRef.current.clear()
    completedTransitionsRef.current.clear()
    responseTransitionsRef.current.clear()
    activeToolCallsRef.current.clear()
    toolCallRevisionsRef.current.clear()
    pendingToolTransitionRef.current = null
    transitionRequestsRef.current.clear()
    audioProducedTransitionsRef.current.clear()
    replayAttemptsRef.current.clear()
    interruptedReplayRef.current = null
    postInterruptionResponseIdRef.current = null
    inputSpeechActiveRef.current = false
    turnIdsRef.current.clear()
    syncedConversationItemsRef.current.clear()
    confirmationPromisesRef.current.clear()
    identificationPromiseRef.current = null
    reconciliationPromiseRef.current = null
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

  const startCompletionCountdown = useCallback(() => {
    if (completionIntervalRef.current !== null) return

    terminalTransitionKeyRef.current = null
    activeTransitionKeyRef.current = null
    audioDoneTransitionKeyRef.current = null
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
    }, 1_000)
  }, [disposeRealtime, reset])

  const armTerminalCompletion = useCallback((transitionKey: string) => {
    if (terminalTransitionKeyRef.current === transitionKey) return
    terminalTransitionKeyRef.current = transitionKey
    audioDoneTransitionKeyRef.current = null
    if (terminalAudioTimeoutRef.current !== null) {
      window.clearTimeout(terminalAudioTimeoutRef.current)
    }
    terminalAudioTimeoutRef.current = window.setTimeout(
      startCompletionCountdown,
      TERMINAL_AUDIO_TIMEOUT_MS,
    )
  }, [startCompletionCountdown])

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
        const snapshot = await promise
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
        if (
          snapshot.result?.next_action === "IDENTIFY" ||
          snapshot.result?.next_action === "COMPLETE"
        ) {
          const realtime = realtimeRef.current
          try {
            if (realtime?.transport.status === "connected") {
              realtime.mute(true)
              setVoiceState("muted")
            }
          } catch {
            // La instantánea recuperada sigue siendo la fuente de verdad.
          }
        }
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
    [reset, updateState],
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

  useEffect(() => {
    if (
      state.result?.next_action !== "IDENTIFY" &&
      state.result?.next_action !== "COMPLETE"
    ) {
      return
    }
    try {
      realtimeRef.current?.mute(true)
    } catch {
      // La navegación y el estado de negocio no dependen del transporte de voz.
    }
  }, [state.result?.next_action])

  useEffect(() => {
    if (
      hydrated &&
      state.result?.next_action === "COMPLETE" &&
      completionSeconds === null &&
      realtimeRef.current?.transport.status !== "connected"
    ) {
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

  const requestTransitionSpeech = useCallback(
    (realtime: RealtimeSession, transition: ControlledTransition): boolean => {
      const interrupted = interruptedReplayRef.current
      if (
        interrupted &&
        interrupted.transition.transitionKey !== transition.transitionKey
      ) {
        const interruptedKey = interrupted.transition.transitionKey
        completedTransitionsRef.current.add(interruptedKey)
        requestedTransitionsRef.current.delete(interruptedKey)
        transitionRequestsRef.current.delete(interruptedKey)
        audioProducedTransitionsRef.current.delete(interruptedKey)
        replayAttemptsRef.current.delete(interruptedKey)
        interruptedReplayRef.current = null
        postInterruptionResponseIdRef.current = null
        if (interruptedReplayTimeoutRef.current !== null) {
          window.clearTimeout(interruptedReplayTimeoutRef.current)
          interruptedReplayTimeoutRef.current = null
        }
      }
      if (
        realtimeRef.current !== realtime ||
        realtime.transport.status !== "connected" ||
        completedTransitionsRef.current.has(transition.transitionKey) ||
        requestedTransitionsRef.current.has(transition.transitionKey)
      ) {
        return false
      }

      requestedTransitionsRef.current.add(transition.transitionKey)
      transitionRequestsRef.current.set(transition.transitionKey, {
        transition,
        revision: businessRevisionRef.current,
      })
      try {
        requestControlledResponse(
          realtime,
          controlledSpeechInstructions(transition.speechText),
          transition.transitionKey,
        )
      } catch (reason) {
        requestedTransitionsRef.current.delete(transition.transitionKey)
        transitionRequestsRef.current.delete(transition.transitionKey)
        throw reason
      }

      if (transition.terminal) {
        armTerminalCompletion(transition.transitionKey)
      }
      return true
    },
    [armTerminalCompletion],
  )

  useEffect(() => {
    const realtime = realtimeRef.current
    if (realtime?.transport.status !== "connected") return
    if (activeToolCallsRef.current.size > 0) return

    let transition: ControlledTransition | null = null
    if (state.result) {
      transition = {
        transitionKey: flowTransitionKey(state.result),
        speechText: state.result.speech_text,
        nextAction: state.result.next_action,
        terminal: state.result.next_action === "COMPLETE",
      }
    } else if (state.analysis) {
      transition = {
        transitionKey: analysisTransitionKey(state.analysis),
        speechText: state.analysis.speech_text,
        nextAction: state.analysis.next_action,
        terminal: false,
      }
    }
    if (!transition) return

    try {
      requestTransitionSpeech(realtime, transition)
    } catch (reason) {
      queueMicrotask(() => {
        setVoiceError(errorMessage(reason))
        setVoiceState("error")
        if (transition.terminal) startCompletionCountdown()
      })
    }
  }, [
    requestTransitionSpeech,
    startCompletionCountdown,
    state.analysis,
    state.result,
    voiceState,
  ])

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
        if (stateRef.current.result?.next_action === "COMPLETE") {
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
        const agent = createKioskRealtimeAgent({
          analyzeRequirement: async (transcript, callId) => {
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
              agentRequirementId = response.requirement_id
              if (!isBusinessSessionCurrent()) return response
              if (
                !shouldApplyAnalysisResponse(
                  stateRef.current,
                  response,
                  startingRequirementId,
                  businessRevisionRef.current !== requestRevision,
                )
              ) {
                return response
              }
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
              } else {
                setVoiceError(errorMessage(reason))
                setVoiceState("error")
              }
              throw reason
            }
          },
          confirmRequirement: async (confirmed) => {
            const requirementId =
              stateRef.current.analysis?.requirement_id ??
              stateRef.current.result?.requirement_id ??
              agentRequirementId
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
                    }),
                  },
                ),
              }
              confirmationPromisesRef.current.set(requestKey, requestEntry)
            }

            try {
              const response = await requestEntry.promise
              if (!isBusinessSessionCurrent()) return response
              if (
                !shouldApplyFlowResponse(
                  stateRef.current,
                  response,
                  requirementId,
                  businessRevisionRef.current !== requestEntry.revision,
                )
              ) {
                return response
              }
              setVoiceError(null)

              if (!confirmed || response.next_action === "CAPTURE") {
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
                return response
              }

              updateState((stored) => ({
                ...stored,
                session: stored.session
                  ? { ...stored.session, status: response.status }
                  : stored.session,
                analysis: null,
                result: response,
                isClarification: false,
              }))
              if (
                response.next_action === "IDENTIFY" ||
                response.next_action === "COMPLETE"
              ) {
                const realtime = realtimeRef.current
                try {
                  if (realtime?.transport.status === "connected") {
                    realtime.mute(true)
                    setVoiceState("muted")
                  }
                } catch {
                  // El estado del flujo y su ruta permanecen recuperables.
                }
              }
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
              } else {
                setVoiceError(errorMessage(reason))
                setVoiceState("error")
              }
              throw reason
            }
          },
        })

        const realtime = new RealtimeSessionClass(agent, {
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
        const clearInterruptedReplay = (consume: boolean) => {
          const pending = interruptedReplayRef.current
          if (!pending) return
          const transitionKey = pending.transition.transitionKey
          if (consume) completedTransitionsRef.current.add(transitionKey)
          requestedTransitionsRef.current.delete(transitionKey)
          transitionRequestsRef.current.delete(transitionKey)
          audioProducedTransitionsRef.current.delete(transitionKey)
          if (consume) replayAttemptsRef.current.delete(transitionKey)
          interruptedReplayRef.current = null
          postInterruptionResponseIdRef.current = null
          if (interruptedReplayTimeoutRef.current !== null) {
            window.clearTimeout(interruptedReplayTimeoutRef.current)
            interruptedReplayTimeoutRef.current = null
          }
        }
        const replayInterruptedTransition = () => {
          interruptedReplayTimeoutRef.current = null
          const pending = interruptedReplayRef.current
          if (!pending || !isCurrentRealtime()) return
          if (
            !shouldReplayControlledTransition(
              stateRef.current,
              pending.transition,
              pending.revision,
              businessRevisionRef.current,
            )
          ) {
            clearInterruptedReplay(true)
            return
          }
          if (
            inputSpeechActiveRef.current ||
            postInterruptionResponseIdRef.current !== null ||
            activeToolCallsRef.current.size > 0
          ) {
            scheduleInterruptedReplay(1_000)
            return
          }

          const transition = pending.transition
          clearInterruptedReplay(false)
          try {
            requestTransitionSpeech(realtime, transition)
          } catch (reason) {
            setVoiceError(errorMessage(reason))
            setVoiceState("error")
            if (transition.terminal) startCompletionCountdown()
          }
        }
        function scheduleInterruptedReplay(delayMs: number) {
          if (!interruptedReplayRef.current) return
          if (interruptedReplayTimeoutRef.current !== null) {
            window.clearTimeout(interruptedReplayTimeoutRef.current)
          }
          interruptedReplayTimeoutRef.current = window.setTimeout(
            replayInterruptedTransition,
            delayMs,
          )
        }
        const queueInterruptedReplay = (
          transitionKey: string,
        ): "queued" | "exhausted" | "unavailable" => {
          const request = transitionRequestsRef.current.get(transitionKey)
          if (!request) return "unavailable"
          const attempts = replayAttemptsRef.current.get(transitionKey) ?? 0
          if (!canReplayControlledSpeech(attempts)) {
            transitionRequestsRef.current.delete(transitionKey)
            audioProducedTransitionsRef.current.delete(transitionKey)
            setVoiceError(
              request.transition.terminal
                ? "No pude reproducir el cierre por voz; el resultado permanece en pantalla."
                : "No pude reproducir el mensaje. Usa Reintentar voz para volver a intentarlo.",
            )
            setVoiceState("error")
            return "exhausted"
          }

          replayAttemptsRef.current.set(transitionKey, attempts + 1)
          interruptedReplayRef.current = request
          postInterruptionResponseIdRef.current = null
          scheduleInterruptedReplay(1_500)
          return "queued"
        }
        const finishControlledPlayback = (interrupted: boolean) => {
          const transitionKey = interrupted
            ? activeTransitionKeyRef.current ?? audioDoneTransitionKeyRef.current
            : audioDoneTransitionKeyRef.current
          if (!transitionKey) {
            setVoiceState(
              activeTransitionKeyRef.current
                ? "speaking"
                : realtime.muted
                  ? "muted"
                  : "listening",
            )
            return
          }
          const audioProduced =
            audioProducedTransitionsRef.current.has(transitionKey)
          activeTransitionKeyRef.current = null
          audioDoneTransitionKeyRef.current = null
          if (!interrupted || audioProduced) {
            completedTransitionsRef.current.add(transitionKey)
            transitionRequestsRef.current.delete(transitionKey)
            audioProducedTransitionsRef.current.delete(transitionKey)
            replayAttemptsRef.current.delete(transitionKey)
            if (
              interruptedReplayRef.current?.transition.transitionKey === transitionKey
            ) {
              interruptedReplayRef.current = null
              postInterruptionResponseIdRef.current = null
              if (interruptedReplayTimeoutRef.current !== null) {
                window.clearTimeout(interruptedReplayTimeoutRef.current)
                interruptedReplayTimeoutRef.current = null
              }
            }
          }

          if (
            (!interrupted || audioProduced) &&
            transitionKey === terminalTransitionKeyRef.current
          ) {
            startCompletionCountdown()
          } else {
            setVoiceState(realtime.muted ? "muted" : "listening")
          }
        }

        realtime.on("history_updated", (history) => {
          if (!isCurrentRealtime()) return
          const nextCaptions = captionsFromHistory(history)
          setCaptions(nextCaptions)
          const session = stateRef.current.session
          const pending = nextCaptions.filter(
            (caption) =>
              caption.completed && !syncedConversationItemsRef.current.has(caption.id),
          )
          if (!session || pending.length === 0) return
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
        realtime.on("agent_tool_start", (_context, _agent, _tool, details) => {
          if (!isCurrentRealtime()) return
          clearInterruptedReplay(true)
          const callKey = toolCallKey(details.toolCall, _tool.name)
          activeToolCallsRef.current.add(callKey)
          toolCallRevisionsRef.current.set(callKey, businessRevisionRef.current)
          try {
            realtime.mute(true)
          } catch {
            // La respuesta autoritativa seguirá controlando la fase del flujo.
          }
          setVoiceState("thinking")
        })
        realtime.on("agent_tool_end", (_context, _agent, _tool, result, details) => {
          if (!isCurrentRealtime()) return
          const callKey = toolCallKey(details.toolCall, _tool.name)
          const startingRevision = toolCallRevisionsRef.current.get(callKey)
          activeToolCallsRef.current.delete(callKey)
          toolCallRevisionsRef.current.delete(callKey)
          const transition = controlledTransitionFromToolResult(result)
          if (
            transition &&
            (businessTransitionKey(stateRef.current) === transition.transitionKey ||
              startingRevision === businessRevisionRef.current)
          ) {
            pendingToolTransitionRef.current = transition
          }
          if (activeToolCallsRef.current.size > 0) return

          const pendingTransition = pendingToolTransitionRef.current
          pendingToolTransitionRef.current = null
          const keepMuted =
            pendingTransition?.nextAction === "IDENTIFY" ||
            pendingTransition?.nextAction === "COMPLETE" ||
            stateRef.current.result?.next_action === "IDENTIFY" ||
            stateRef.current.result?.next_action === "COMPLETE"
          try {
            realtime.mute(keepMuted)
          } catch {
            // La ruta visual no depende de poder cambiar el track de entrada.
          }
          if (!pendingTransition) {
            setVoiceState(keepMuted ? "muted" : "listening")
            return
          }
          try {
            requestTransitionSpeech(realtime, pendingTransition)
          } catch (reason) {
            setVoiceError(errorMessage(reason))
            setVoiceState("error")
            if (pendingTransition.terminal) startCompletionCountdown()
          }
        })
        realtime.on("audio_start", () => {
          if (!isCurrentRealtime()) return
          setVoiceState("speaking")
        })
        realtime.on("audio_stopped", () => {
          if (!isCurrentRealtime()) return
          // El SDK emite este evento al terminar de generar, no necesariamente al
          // terminar la reproducción WebRTC. La transición controlada se completa
          // con output_audio_buffer.stopped.
          if (!audioDoneTransitionKeyRef.current) {
            setVoiceState(realtime.muted ? "muted" : "listening")
          }
        })
        realtime.on("audio_interrupted", () => {
          if (!isCurrentRealtime()) return
          // Si todavía no se produjo audio, se difiere un único reintento hasta
          // que termine el turno que causó la interrupción.
          finishControlledPlayback(true)
        })
        realtime.on("transport_event", (event) => {
          if (!isCurrentRealtime()) return
          if (event.type === "response.created") {
            const responseId = event.response?.id
            const transitionKey = event.response?.metadata?.[TRANSITION_METADATA_KEY]
            if (
              typeof responseId === "string" &&
              typeof transitionKey === "string"
            ) {
              responseTransitionsRef.current.set(responseId, transitionKey)
              setVoiceState("speaking")
            } else if (
              typeof responseId === "string" &&
              interruptedReplayRef.current
            ) {
              postInterruptionResponseIdRef.current = responseId
              if (interruptedReplayTimeoutRef.current !== null) {
                window.clearTimeout(interruptedReplayTimeoutRef.current)
                interruptedReplayTimeoutRef.current = null
              }
            }
          } else if (event.type === "response.output_audio.delta") {
            const transitionKey = responseTransitionsRef.current.get(event.response_id)
            if (transitionKey) {
              audioProducedTransitionsRef.current.add(transitionKey)
              activeTransitionKeyRef.current = transitionKey
            }
          } else if (event.type === "response.output_audio.done") {
            const transitionKey = responseTransitionsRef.current.get(event.response_id)
            if (transitionKey) {
              audioDoneTransitionKeyRef.current = transitionKey
              activeTransitionKeyRef.current = transitionKey
              responseTransitionsRef.current.delete(event.response_id)
            }
          } else if (event.type === "response.done") {
            const responseId = event.response.id
            if (typeof responseId === "string") {
              if (postInterruptionResponseIdRef.current === responseId) {
                postInterruptionResponseIdRef.current = null
                scheduleInterruptedReplay(250)
              }

              const transitionKey = responseTransitionsRef.current.get(responseId)
              if (
                transitionKey &&
                event.response.status &&
                event.response.status !== "completed"
              ) {
                let waitingForReplay =
                  interruptedReplayRef.current?.transition.transitionKey ===
                  transitionKey
                let replayExhausted = false
                if (
                  !waitingForReplay &&
                  !audioProducedTransitionsRef.current.has(transitionKey)
                ) {
                  const replayStatus = queueInterruptedReplay(transitionKey)
                  waitingForReplay = replayStatus === "queued"
                  replayExhausted = replayStatus === "exhausted"
                }
                if (!waitingForReplay && !replayExhausted) {
                  requestedTransitionsRef.current.delete(transitionKey)
                  transitionRequestsRef.current.delete(transitionKey)
                  audioProducedTransitionsRef.current.delete(transitionKey)
                  replayAttemptsRef.current.delete(transitionKey)
                }
                responseTransitionsRef.current.delete(responseId)
                if (activeTransitionKeyRef.current === transitionKey) {
                  activeTransitionKeyRef.current = null
                }
                if (audioDoneTransitionKeyRef.current === transitionKey) {
                  audioDoneTransitionKeyRef.current = null
                }
                if (
                  transitionKey === terminalTransitionKeyRef.current &&
                  !waitingForReplay
                ) {
                  startCompletionCountdown()
                }
              } else if (
                transitionKey &&
                !audioProducedTransitionsRef.current.has(transitionKey)
              ) {
                const replayStatus = queueInterruptedReplay(transitionKey)
                responseTransitionsRef.current.delete(responseId)
                activeTransitionKeyRef.current = null
                if (replayStatus === "unavailable") {
                  requestedTransitionsRef.current.delete(transitionKey)
                  transitionRequestsRef.current.delete(transitionKey)
                  replayAttemptsRef.current.delete(transitionKey)
                } else if (
                  replayStatus === "exhausted" &&
                  transitionKey === terminalTransitionKeyRef.current
                ) {
                  startCompletionCountdown()
                }
              }
            }
          } else if (event.type === "output_audio_buffer.stopped") {
            finishControlledPlayback(false)
          } else if (event.type === "output_audio_buffer.cleared") {
            finishControlledPlayback(true)
          } else if (event.type === "input_audio_buffer.speech_started") {
            inputSpeechActiveRef.current = true
            setVoiceState("listening")
          } else if (event.type === "input_audio_buffer.speech_stopped") {
            inputSpeechActiveRef.current = false
            if (
              interruptedReplayRef.current &&
              postInterruptionResponseIdRef.current === null
            ) {
              scheduleInterruptedReplay(4_000)
            }
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
            void reconcileSession(activeSession).catch(() => {
              // El error de transporte ya es visible y se podrá reintentar manualmente.
            })
            if (terminalTransitionKeyRef.current) {
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
          requestTransitionSpeech(realtime, {
            transitionKey: flowTransitionKey(snapshot.result),
            speechText: snapshot.result.speech_text,
            nextAction: snapshot.result.next_action,
            terminal: false,
          })
        } else if (snapshot.analysis?.next_action === "CONFIRM") {
          requestTransitionSpeech(realtime, {
            transitionKey: analysisTransitionKey(snapshot.analysis),
            speechText: snapshot.analysis.speech_text,
            nextAction: snapshot.analysis.next_action,
            terminal: false,
          })
        } else if (snapshot.analysis?.next_action === "CLARIFY") {
          requestTransitionSpeech(realtime, {
            transitionKey: analysisTransitionKey(snapshot.analysis),
            speechText: snapshot.analysis.speech_text,
            nextAction: snapshot.analysis.next_action,
            terminal: false,
          })
        } else if (snapshot.result?.next_action === "CAPTURE") {
          requestTransitionSpeech(realtime, {
            transitionKey: flowTransitionKey(snapshot.result),
            speechText: snapshot.result.speech_text,
            nextAction: snapshot.result.next_action,
            terminal: false,
          })
        } else {
          requestTransitionSpeech(realtime, {
            transitionKey: `${activeSession.session_id}:WELCOME`,
            speechText:
              "Hola, soy tu asistente virtual. ¿En qué puedo ayudarte hoy?",
            nextAction: "WELCOME",
            terminal: false,
          })
        }
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
    disposeRealtime,
    handleExpiredSession,
    reconcileSession,
    requestTransitionSpeech,
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
        // El flujo de negocio ya fue confirmado; la sincronización podrá omitirse sin duplicarlo.
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
      syncTextExchange(activeSession, transcript.trim(), response.speech_text)
      return response
    },
    [handleExpiredSession, syncTextExchange, updateState],
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
      syncTextExchange(
        activeSession,
        confirmed ? "Sí, confirmo." : "No, quiero corregir.",
        response.speech_text,
      )
      return response
    },
    [handleExpiredSession, syncTextExchange, updateState],
  )

  const submitIdentification = useCallback(
    async (identifier: string) => {
      const activeSession = stateRef.current.session
      if (!activeSession) throw new Error("No existe una sesión activa")

      if (identificationPromiseRef.current) {
        return identificationPromiseRef.current
      }

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

        const realtime = realtimeRef.current
        if (realtime?.transport.status === "connected") {
          try {
            realtime.mute(true)
            setVoiceState("muted")
            requestTransitionSpeech(realtime, {
              transitionKey: flowTransitionKey(completed),
              speechText: completed.speech_text,
              nextAction: completed.next_action,
              terminal: completed.next_action === "COMPLETE",
            })
          } catch {
            setVoiceError(
              "No fue posible reproducir el cierre por voz; el resultado permanece en pantalla.",
            )
            startCompletionCountdown()
          }
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
      handleExpiredSession,
      requestTransitionSpeech,
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
      selectInteractionMode,
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
      reset,
      retryVoice,
      selectInteractionMode,
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
  if (!value) throw new Error("useKiosk requiere KioskProvider")
  return value
}
