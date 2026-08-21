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
  APPLICATION_EVENT_PREFIX,
  analysisSpeechPlan,
  captionsFromHistory,
  isTerminalFlowResult,
  kioskRouteForState,
  missingVerbatim,
  selectAuthoritativeTranscript,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
  type ConversationCaption,
} from "@/lib/kiosk-realtime"
import type {
  FlowResult,
  KioskSession,
  KioskSessionStatus,
  SpeechPlan,
  TurnAnalysis,
} from "@/lib/types"

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
const FOLLOW_UP_WINDOW_MS = 45_000
// How long a tool waits for the session's audio transcription of the turn to land. The
// transcription usually arrives around the same time as the tool call, so this is a settle
// window, not a poll loop: the common case resolves on the first check. On timeout the tool
// tells the model to ask the person to repeat -- there is no second-best transcript to fall
// back to, and inventing one is exactly the bug this replaced.
const TRANSCRIPT_SETTLE_TIMEOUT_MS = 1_500
const TRANSCRIPT_SETTLE_INTERVAL_MS = 100

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

// A short state summary handed to the model after a reconnect, so it can pick the
// conversation back up in its own words instead of the application replaying a script at it.
// APPLICATION_EVENT_PREFIX keeps it off the caption strip.
function resumeContext(state: KioskState): string | null {
  const { analysis, result } = state
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
  const activeToolCallsRef = useRef(new Set<string>())
  const turnIdsRef = useRef(new Map<string, string>())
  const syncedConversationItemsRef = useRef(new Set<string>())
  const userCaptionsRef = useRef<ConversationCaption[]>([])
  const consumedTranscriptItemsRef = useRef(new Set<string>())
  // Strings the last tool result said must be spoken word for word, and whether the one
  // permitted correction has already been spent on them.
  const pendingVerbatimRef = useRef<string[]>([])
  const verbatimRetriedRef = useRef(false)
  const verbatimBaselineRef = useRef(new Set<string>())
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
    activeToolCallsRef.current.clear()
    pendingVerbatimRef.current = []
    verbatimRetriedRef.current = false
    verbatimBaselineRef.current.clear()
  }, [])

  const clearFlowTracking = useCallback(() => {
    clarificationRef.current = false
    activeToolCallsRef.current.clear()
    pendingVerbatimRef.current = []
    verbatimRetriedRef.current = false
    verbatimBaselineRef.current.clear()
    turnIdsRef.current.clear()
    syncedConversationItemsRef.current.clear()
    userCaptionsRef.current = []
    consumedTranscriptItemsRef.current.clear()
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
    followUpTimeoutRef.current = window.setTimeout(
      startCompletionCountdown,
      FOLLOW_UP_WINDOW_MS,
    )
  }, [startCompletionCountdown])

  const armTerminalCompletion = useCallback(() => {
    if (terminalAudioTimeoutRef.current !== null) return
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

  // The only two places the microphone is closed. IDENTIFY is a credential window -- nothing
  // should be captured while someone types their CI -- and a terminal result means an
  // executive owns the case from here. Everywhere else, including while a tool runs, the mic
  // stays live so the customer can interrupt, correct or add something.
  useEffect(() => {
    const credentialEntry = state.result?.next_action === "IDENTIFY"
    const handedOff = state.result ? isTerminalFlowResult(state.result) : false
    const declined = state.analysis?.next_action === "DECLINE"
    if (!credentialEntry && !handedOff && !declined) return
    try {
      if (realtimeRef.current?.transport.status === "connected") {
        realtimeRef.current.mute(true)
        // Deferred out of the effect body: closing the microphone is the external change
        // this effect exists to make, and reflecting it in the UI is a consequence of that,
        // not part of it.
        queueMicrotask(() => setVoiceState("muted"))
      }
    } catch {
      // Navigation and business state do not depend on the voice transport.
    }
    if (handedOff || declined) armTerminalCompletion()
  }, [armTerminalCompletion, state.result, state.analysis?.next_action])

  useEffect(() => {
    if (
      hydrated &&
      state.result?.next_action === "COMPLETE" &&
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

  // The only record of what the customer said is the voice session's own transcription. It
  // normally lands within a few hundred milliseconds of the tool call, so wait a bounded
  // moment; if it never arrives, say so rather than inventing a transcript.
  const resolveTurnTranscript = useCallback(async (): Promise<string | null> => {
    const deadline = Date.now() + TRANSCRIPT_SETTLE_TIMEOUT_MS
    for (;;) {
      const selection = selectAuthoritativeTranscript(
        userCaptionsRef.current,
        consumedTranscriptItemsRef.current,
      )
      if (selection) {
        selection.itemIds.forEach((itemId) =>
          consumedTranscriptItemsRef.current.add(itemId),
        )
        return selection.text
      }
      if (Date.now() >= deadline) return null
      await new Promise((resolve) =>
        window.setTimeout(resolve, TRANSCRIPT_SETTLE_INTERVAL_MS),
      )
    }
  }, [])

  // Everything the model has already said is baseline: a check must measure only what comes
  // out after this tool result, not the whole conversation so far.
  const rememberVerbatim = useCallback((plan: SpeechPlan | undefined) => {
    pendingVerbatimRef.current = plan?.verbatim ?? []
    verbatimRetriedRef.current = false
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

        // The persona, model and voice all come from the secret the backend minted. There is
        // no fallback on purpose: a missing field means the backend changed shape, and
        // silently connecting with SDK defaults would swap the kiosk's persona and model for
        // something nobody chose.
        const { model, instructions, voice } = secret.session ?? {}
        if (!model || !instructions || !voice) {
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
        const agent = createKioskRealtimeAgent(
          {
            resolveSpokenText: resolveTurnTranscript,
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
                cancelFollowUpWindow()
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
                rememberVerbatim(analysisSpeechPlan(response))
                if (!isBusinessSessionCurrent()) return response
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
                    return response
                  }
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
                  if (!isTerminalFlowResult(completedFlow)) armFollowUpWindow()
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
                rememberVerbatim(response.speech_plan)
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
                }
                throw reason
              }
            },
          },
          { instructions, voice },
        )

        const realtime = new RealtimeSessionClass(agent, {
          model,
          historyStoreAudio: false,
          tracingDisabled: true,
          config: {
            outputModalities: ["audio"],
            // One tool at a time: both tools advance the same backend state machine, and
            // letting them run concurrently would race a confirmation against the analysis
            // it confirms.
            parallelToolCalls: false,
            audio: {
              input: {
                noiseReduction: { type: "near_field" },
                // Mirrors the minted session (openai_provider.create_realtime_client_secret).
                // The SDK sends its own session.update on connect, so leaving these out here
                // would replace the backend's choices with SDK defaults rather than preserve
                // them.
                transcription: { model: "gpt-realtime-whisper", language: "es" },
                // The model runs its own turn-taking: it answers when the customer stops and
                // stops when the customer starts. Nothing suppresses the responses it decides
                // to make.
                turnDetection: {
                  type: "semantic_vad",
                  eagerness: "auto",
                  createResponse: true,
                  interruptResponse: true,
                },
              },
              output: { voice },
            },
          },
        })
        realtimeRef.current = realtime
        const isCurrentRealtime = () =>
          isActiveAttempt() && realtimeRef.current === realtime

        const settleVoiceState = () => {
          if (activeToolCallsRef.current.size > 0) return
          setVoiceState(realtime.muted ? "muted" : "listening")
        }

        // The one guard kept from the old controlled-speech machine, at a fraction of its
        // size. When a tool result carried strings that must survive word for word -- a
        // grounded answer, the credential warning, an executive's name -- check the model
        // actually said them once its turn is over, and spend at most one correction on it.
        // Anything past that is a visible failure with the result still on screen, not an
        // endless re-read loop.
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

          const missing = missingVerbatim(spoken, required)
          if (missing.length === 0) {
            pendingVerbatimRef.current = []
            return
          }
          if (verbatimRetriedRef.current) {
            pendingVerbatimRef.current = []
            setVoiceError(
              "No pude decirte parte del mensaje; el detalle completo está en pantalla.",
            )
            return
          }
          verbatimRetriedRef.current = true
          // The correction is measured on its own, not against the turn that fell short.
          verbatimBaselineRef.current = new Set(
            userCaptionsRef.current
              .filter((caption) => caption.role === "assistant")
              .map((caption) => caption.id),
          )
          try {
            // Pushed as a conversation item, never as `response.instructions`. Those
            // *replace* the session instructions for the response they belong to, so a
            // correction sent that way would be spoken by a model that had lost its
            // persona, its register and its safety rules for exactly that turn -- which is
            // how this kiosk ended up sounding like a text-to-speech engine in the first
            // place. A context item adds to the conversation and triggers a reply under the
            // full session prompt.
            realtime.sendMessage(
              `${APPLICATION_EVENT_PREFIX} Te faltó decir esto tal cual: ${JSON.stringify(
                missing.join(" "),
              )}. Dilo ahora, palabra por palabra, sin agregar nada más.`,
            )
          } catch {
            pendingVerbatimRef.current = []
          }
        }

        realtime.on("history_updated", (history) => {
          if (!isCurrentRealtime()) return
          const nextCaptions = captionsFromHistory(history)
          setCaptions(nextCaptions)
          userCaptionsRef.current = nextCaptions
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
        realtime.on("agent_tool_start", (_context, _agent, _tool, details) => {
          if (!isCurrentRealtime()) return
          // The microphone stays live. A backend round-trip takes several seconds, and the
          // customer must be able to interrupt, correct or add something during it.
          activeToolCallsRef.current.add(toolCallKey(details.toolCall, _tool.name))
          setVoiceState("thinking")
        })
        realtime.on("agent_tool_end", (_context, _agent, _tool, _result, details) => {
          if (!isCurrentRealtime()) return
          activeToolCallsRef.current.delete(toolCallKey(details.toolCall, _tool.name))
          settleVoiceState()
        })
        realtime.on("audio_start", () => {
          if (!isCurrentRealtime()) return
          setVoiceState("speaking")
        })
        realtime.on("audio_stopped", () => {
          if (!isCurrentRealtime()) return
          checkVerbatim()
          settleVoiceState()
        })
        realtime.on("audio_interrupted", () => {
          if (!isCurrentRealtime()) return
          // The customer talked over the kiosk. That is a supported way to use it, not a
          // failure: nothing is replayed, and a verbatim string the model was cut off from
          // saying is dropped rather than forced through a second time.
          pendingVerbatimRef.current = []
          verbatimBaselineRef.current.clear()
          setVoiceState("listening")
        })
        realtime.on("transport_event", (event) => {
          if (!isCurrentRealtime()) return
          if (event.type === "output_audio_buffer.stopped") {
            // Fires after playback actually finishes, later than `audio_stopped` -- by which
            // point the transcript of the turn has usually landed. The check is idempotent,
            // so running it at both moments only makes it more likely to see the text at all.
            checkVerbatim()
            settleVoiceState()
          } else if (event.type === "input_audio_buffer.speech_started") {
            setVoiceState("listening")
          } else if (event.type === "input_audio_buffer.speech_stopped") {
            if (activeToolCallsRef.current.size === 0) setVoiceState("thinking")
          }
        })
        realtime.on("error", ({ error }) => {
          if (!isCurrentRealtime()) return
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

        // Hand the model the state it is resuming into, if any, and let it open its mouth.
        // No instructions override, no fixed greeting: the persona on the session already
        // says to introduce itself and ask what the person needs, and it words that itself.
        const resume = resumeContext(stateRef.current)
        if (resume) {
          realtime.sendMessage(`${APPLICATION_EVENT_PREFIX} ${resume}`)
        } else {
          realtime.transport.sendEvent({ type: "response.create" })
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
    armFollowUpWindow,
    cancelFollowUpWindow,
    disposeRealtime,
    handleExpiredSession,
    reconcileSession,
    rememberVerbatim,
    resolveTurnTranscript,
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
      syncTextExchange(activeSession, transcript.trim(), response.speech_text)
      return response
    },
    [cancelFollowUpWindow, handleExpiredSession, syncTextExchange, updateState],
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
          // The CI is in; the microphone opens again so the model can say how it ends and
          // the customer can react. The mic-policy effect closes it once the result lands as
          // terminal, and the terminal timeout finishes the session either way.
          rememberVerbatim(completed.speech_plan)
          try {
            realtime.mute(false)
            // A context item, not `response.instructions` -- see the note in checkVerbatim
            // above for why the difference matters.
            realtime.sendMessage(
              `${APPLICATION_EVENT_PREFIX} Ya escribió su CI y el trámite quedó resuelto. ` +
                "Dile cómo termina usando lo que te devolvió la última herramienta y despídete.",
            )
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
      rememberVerbatim,
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
  if (!value) throw new Error("useKiosk requires KioskProvider")
  return value
}
