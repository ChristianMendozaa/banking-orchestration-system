"use client"

import { apiRequest } from "@/lib/api"
import type { FlowResult, KioskSession, TurnAnalysis } from "@/lib/types"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"

const STORAGE_KEY = "orquestacion_kiosk_flow_v1"

interface KioskState {
  session: KioskSession | null
  transcript: string
  analysis: TurnAnalysis | null
  result: FlowResult | null
  isClarification: boolean
}

const emptyState: KioskState = {
  session: null,
  transcript: "",
  analysis: null,
  result: null,
  isClarification: false,
}

interface KioskContextValue extends KioskState {
  hydrated: boolean
  beginSession: (preferentialAttention: boolean) => Promise<void>
  setTranscript: (value: string) => void
  setAnalysis: (value: TurnAnalysis | null) => void
  setResult: (value: FlowResult | null) => void
  setIsClarification: (value: boolean) => void
  reset: () => void
  sessionRequest: <T>(path: string, init?: RequestInit) => Promise<T>
}

const KioskContext = createContext<KioskContextValue | null>(null)

export function KioskProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<KioskState>(emptyState)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    queueMicrotask(() => {
      const raw = sessionStorage.getItem(STORAGE_KEY)
      if (raw) {
        try {
          const restored = JSON.parse(raw) as KioskState
          if (restored.session && new Date(restored.session.expires_at) > new Date()) {
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

  const beginSession = useCallback(async (preferentialAttention: boolean) => {
    const session = await apiRequest<KioskSession>("/kiosk/sessions", {
      method: "POST",
      body: JSON.stringify({ preferential_attention: preferentialAttention }),
    })
    setState({ ...emptyState, session })
  }, [])

  const sessionRequest = useCallback(
    async <T,>(path: string, init: RequestInit = {}) => {
      if (!state.session) throw new Error("No existe una sesión activa")
      const headers = new Headers(init.headers)
      headers.set("X-Session-Token", state.session.session_token)
      return apiRequest<T>(`/kiosk/sessions/${state.session.session_id}${path}`, {
        ...init,
        headers,
      })
    },
    [state.session],
  )

  const value = useMemo<KioskContextValue>(
    () => ({
      ...state,
      hydrated,
      beginSession,
      setTranscript: (transcript) => setState((current) => ({ ...current, transcript })),
      setAnalysis: (analysis) => setState((current) => ({ ...current, analysis })),
      setResult: (result) => setState((current) => ({ ...current, result })),
      setIsClarification: (isClarification) =>
        setState((current) => ({ ...current, isClarification })),
      reset: () => setState(emptyState),
      sessionRequest,
    }),
    [beginSession, hydrated, sessionRequest, state],
  )

  return <KioskContext.Provider value={value}>{children}</KioskContext.Provider>
}

export function useKiosk(): KioskContextValue {
  const value = useContext(KioskContext)
  if (!value) throw new Error("useKiosk requiere KioskProvider")
  return value
}

export function speak(text: string): void {
  if (!text || typeof window === "undefined" || !("speechSynthesis" in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = "es-BO"
  utterance.rate = 0.95
  window.speechSynthesis.speak(utterance)
}
