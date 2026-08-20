"use client"

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

import { useRuntimeConfig } from "@/components/providers/app-providers"
import { ApiError, errorMessage } from "@/lib/api"
import { createKioskSession, kioskSessionRequest } from "@/lib/kiosk-api"
import {
  isTerminalFlowResult,
  kioskRouteForState,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
} from "@/lib/kiosk-flow"
import { KioskVoiceConnection, type VoiceCaption } from "@/lib/kiosk-voice"
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
// How long the kiosk keeps listening after answering a question by itself, before it
// finishes the session on its own. It is waiting for a person to decide whether they have
// another question, not for audio to finish playing.
const FOLLOW_UP_WINDOW_MS = 45_000
// A terminal result the backend never followed with `session.finished` -- a dropped socket,
// most likely. The result is already on screen either way; this only decides when the kiosk
// resets itself for the next person.
const TERMINAL_TIMEOUT_MS = 30_000

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
  captions: VoiceCaption[]
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

export function KioskProvider({ children }: { children: React.ReactNode }) {
  // Empty when the backend is reachable on the page's own origin, which is the shape of a
  // single-reverse-proxy deployment.
  const { voiceBaseUrl } = useRuntimeConfig()
  const router = useRouter()
  const pathname = usePathname()
  const [state, setState] = useState<KioskState>(emptyState)
  const [hydrated, setHydrated] = useState(false)
  const [voiceState, setVoiceState] = useState<VoiceState>("idle")
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [captions, setCaptions] = useState<VoiceCaption[]>([])
  const [completionSeconds, setCompletionSeconds] = useState<number | null>(null)

  const stateRef = useRef(state)
  const businessRevisionRef = useRef(0)
  const voiceRef = useRef<KioskVoiceConnection | null>(null)
  const connectPromiseRef = useRef<Promise<void> | null>(null)
  const connectionAttemptRef = useRef(0)
  const clarificationRef = useRef(false)
  const identificationPromiseRef = useRef<Promise<FlowResult> | null>(null)
  const reconciliationPromiseRef = useRef<{
    sessionId: string
    revision: number
    promise: Promise<KioskSessionStatus>
  } | null>(null)
  const completionIntervalRef = useRef<number | null>(null)
  const terminalTimeoutRef = useRef<number | null>(null)
  const followUpTimeoutRef = useRef<number | null>(null)
  const followUpTransitionKeyRef = useRef<string | null>(null)

  const updateState = useCallback((updater: (current: KioskState) => KioskState) => {
    const next = updater(stateRef.current)
    businessRevisionRef.current += 1
    stateRef.current = next
    setState(next)
  }, [])

  const clearTimers = useCallback(() => {
    for (const ref of [terminalTimeoutRef, followUpTimeoutRef]) {
      if (ref.current !== null) {
        window.clearTimeout(ref.current)
        ref.current = null
      }
    }
    if (completionIntervalRef.current !== null) {
      window.clearInterval(completionIntervalRef.current)
      completionIntervalRef.current = null
    }
    followUpTransitionKeyRef.current = null
  }, [])

  const disposeVoice = useCallback(() => {
    connectionAttemptRef.current += 1
    const voice = voiceRef.current
    voiceRef.current = null
    connectPromiseRef.current = null
    voice?.close()
  }, [])

  const reset = useCallback(() => {
    clearTimers()
    disposeVoice()
    clarificationRef.current = false
    identificationPromiseRef.current = null
    reconciliationPromiseRef.current = null
    setCaptions([])
    setVoiceError(null)
    setVoiceState("idle")
    setCompletionSeconds(null)
    updateState(() => emptyState)
  }, [clearTimers, disposeVoice, updateState])

  const startCompletionCountdown = useCallback(() => {
    if (completionIntervalRef.current !== null) return
    clearTimers()
    disposeVoice()
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
  }, [clearTimers, disposeVoice, reset])

  const cancelFollowUpWindow = useCallback(() => {
    if (followUpTimeoutRef.current !== null) {
      window.clearTimeout(followUpTimeoutRef.current)
      followUpTimeoutRef.current = null
    }
    followUpTransitionKeyRef.current = null
  }, [])

  const armFollowUpWindow = useCallback(
    (key: string) => {
      if (followUpTransitionKeyRef.current === key) return
      followUpTransitionKeyRef.current = key
      if (followUpTimeoutRef.current !== null) {
        window.clearTimeout(followUpTimeoutRef.current)
      }
      followUpTimeoutRef.current = window.setTimeout(
        startCompletionCountdown,
        FOLLOW_UP_WINDOW_MS,
      )
    },
    [startCompletionCountdown],
  )

  // ---------------------------------------------------------------- reducers
  //
  // Voice and text funnel through these. That is the point of the change: the socket hands
  // back the same TurnAnalysis / FlowResult the HTTP endpoints do, because on the backend
  // it is the same orchestrator call. There is no longer a voice-shaped copy of the flow.

  const applyAnalysis = useCallback(
    (response: TurnAnalysis, startingRequirementId: string | null, revision: number) => {
      if (response.next_action === "COMPLETE" && response.result) {
        return response.result
      }
      if (
        !shouldApplyAnalysisResponse(
          stateRef.current,
          response,
          startingRequirementId,
          businessRevisionRef.current !== revision,
        )
      ) {
        return null
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
      return null
    },
    [updateState],
  )

  const applyFlow = useCallback(
    (response: FlowResult, startingRequirementId: string, revision: number) => {
      if (
        !shouldApplyFlowResponse(
          stateRef.current,
          response,
          startingRequirementId,
          businessRevisionRef.current !== revision,
        )
      ) {
        return
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
    },
    [updateState],
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
            if (restored.session && new Date(restored.session.expires_at) > new Date()) {
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

  // A terminal result ends the session; an automatic answer deliberately does not, so the
  // microphone stays open for a follow-up until the window closes.
  useEffect(() => {
    const result = state.result
    if (!result) return
    if (isTerminalFlowResult(result) || state.analysis?.next_action === "DECLINE") {
      if (terminalTimeoutRef.current === null) {
        terminalTimeoutRef.current = window.setTimeout(
          startCompletionCountdown,
          TERMINAL_TIMEOUT_MS,
        )
      }
      return
    }
    if (result.next_action === "COMPLETE" && result.resolution_type === "AUTOMATIC") {
      armFollowUpWindow(result.requirement_id)
    }
  }, [armFollowUpWindow, startCompletionCountdown, state.analysis, state.result])

  useEffect(
    () => () => {
      clearTimers()
      disposeVoice()
    },
    [clearTimers, disposeVoice],
  )

  const beginSession = useCallback(
    async (preferentialAttention: boolean) => {
      clearTimers()
      disposeVoice()
      clarificationRef.current = false
      identificationPromiseRef.current = null
      setCaptions([])
      setVoiceError(null)
      setVoiceState("idle")
      setCompletionSeconds(null)
      updateState(() => emptyState)
      const session = await createKioskSession(preferentialAttention)
      updateState(() => ({ ...emptyState, session }))
    },
    [clearTimers, disposeVoice, updateState],
  )

  const handleExpiredSession = useCallback(() => {
    reset()
  }, [reset])

  const connectVoice = useCallback(async () => {
    if (voiceRef.current) return
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
      try {
        const reconciled = await reconcileSession(activeSession)
        if (!isActiveAttempt() || !reconciled) return
        const completed = stateRef.current.result
        if (completed && isTerminalFlowResult(completed)) {
          setVoiceState("idle")
          return
        }

        setVoiceState("connecting")
        const voice = new KioskVoiceConnection({
          onState: (value) => {
            if (isActiveAttempt()) setVoiceState(value)
          },
          onCaptions: (next) => {
            if (isActiveAttempt()) setCaptions(next)
          },
          onAnalysis: (analysis) => {
            if (!isActiveAttempt()) return
            cancelFollowUpWindow()
            const startingRequirementId =
              stateRef.current.analysis?.requirement_id ?? null
            const embedded = applyAnalysis(
              analysis,
              startingRequirementId,
              businessRevisionRef.current,
            )
            if (embedded) {
              applyFlow(
                embedded,
                startingRequirementId ?? embedded.requirement_id,
                businessRevisionRef.current,
              )
            }
          },
          onResult: (result) => {
            if (!isActiveAttempt()) return
            cancelFollowUpWindow()
            applyFlow(result, result.requirement_id, businessRevisionRef.current)
          },
          onFinished: () => {
            if (isActiveAttempt()) startCompletionCountdown()
          },
          onError: (message) => {
            if (!isActiveAttempt()) return
            setVoiceError(message)
            setVoiceState("error")
          },
        })
        voiceRef.current = voice
        await voice.connect(activeSession, voiceBaseUrl || window.location.origin)
        if (!isActiveAttempt()) {
          voice.close()
          return
        }
        setVoiceState("listening")
      } catch (reason) {
        if (attemptId !== connectionAttemptRef.current) return
        disposeVoice()
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
    applyAnalysis,
    applyFlow,
    cancelFollowUpWindow,
    disposeVoice,
    handleExpiredSession,
    reconcileSession,
    startCompletionCountdown,
    voiceBaseUrl,
  ])

  const retryVoice = useCallback(async () => {
    disposeVoice()
    setVoiceError(null)
    setVoiceState("idle")
    await connectVoice()
  }, [connectVoice, disposeVoice])

  const selectInteractionMode = useCallback(
    (mode: "voice" | "text") => {
      if (mode === "text") {
        disposeVoice()
        setVoiceError(null)
        setVoiceState("idle")
      }
      updateState((stored) => ({ ...stored, interactionMode: mode }))
    },
    [disposeVoice, updateState],
  )

  const syncTextExchange = useCallback(
    (activeSession: KioskSession, customerText: string, assistantText: string) => {
      void kioskSessionRequest(activeSession, "/conversation/messages", {
        method: "POST",
        body: JSON.stringify({
          messages: [
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
          ],
        }),
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
      const revision = businessRevisionRef.current
      const startingRequirementId = stateRef.current.analysis?.requirement_id ?? null
      let response: TurnAnalysis
      try {
        cancelFollowUpWindow()
        response = await kioskSessionRequest<TurnAnalysis>(activeSession, "/turns", {
          method: "POST",
          body: JSON.stringify({
            turn_id: crypto.randomUUID(),
            transcript: transcript.trim(),
            is_clarification: clarificationRef.current,
          }),
        })
      } catch (reason) {
        if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
          handleExpiredSession()
        }
        throw reason
      }
      if (stateRef.current.session?.session_id !== activeSession.session_id) {
        return response
      }
      const embedded = applyAnalysis(response, startingRequirementId, revision)
      if (embedded) {
        applyFlow(embedded, startingRequirementId ?? embedded.requirement_id, revision)
      }
      syncTextExchange(activeSession, transcript.trim(), response.speech_text)
      return response
    },
    [
      applyAnalysis,
      applyFlow,
      cancelFollowUpWindow,
      handleExpiredSession,
      syncTextExchange,
    ],
  )

  const confirmText = useCallback(
    async (confirmed: boolean): Promise<FlowResult> => {
      const activeSession = stateRef.current.session
      const requirementId = stateRef.current.analysis?.requirement_id
      if (!activeSession || !requirementId) {
        throw new Error("No existe un requerimiento pendiente de confirmación")
      }
      const revision = businessRevisionRef.current
      let response: FlowResult
      try {
        response = await kioskSessionRequest<FlowResult>(activeSession, "/confirmation", {
          method: "POST",
          body: JSON.stringify({ requirement_id: requirementId, confirmed }),
        })
      } catch (reason) {
        if (reason instanceof ApiError && reason.code === "SESSION_EXPIRED") {
          handleExpiredSession()
        }
        throw reason
      }
      if (stateRef.current.session?.session_id !== activeSession.session_id) {
        return response
      }
      applyFlow(response, requirementId, revision)
      syncTextExchange(
        activeSession,
        confirmed ? "Sí, confirmo." : "No, quiero corregir.",
        response.speech_text,
      )
      return response
    },
    [applyFlow, handleExpiredSession, syncTextExchange],
  )

  const submitIdentification = useCallback(
    async (identifier: string) => {
      const activeSession = stateRef.current.session
      if (!activeSession) throw new Error("No existe una sesión activa")
      if (identificationPromiseRef.current) return identificationPromiseRef.current

      const revision = businessRevisionRef.current
      const request = kioskSessionRequest<FlowResult>(activeSession, "/identification", {
        method: "POST",
        body: JSON.stringify({ identifier: identifier.trim() }),
      })
      identificationPromiseRef.current = request

      try {
        const completed = await request
        if (stateRef.current.session?.session_id !== activeSession.session_id) {
          return completed
        }
        applyFlow(completed, completed.requirement_id, revision)
        // Identification is the one step that happens off the socket -- the CI is typed
        // into a protected field, never dictated -- so the voice session has to be told
        // the flow moved on before it can speak the outcome.
        if (voiceRef.current) {
          voiceRef.current.resync()
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
    [applyFlow, handleExpiredSession, startCompletionCountdown],
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
      confirmText,
      connectVoice,
      hydrated,
      reset,
      retryVoice,
      selectInteractionMode,
      state,
      submitIdentification,
      submitTextTurn,
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
