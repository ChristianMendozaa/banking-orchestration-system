import type { RealtimeItem } from "@openai/agents/realtime"

import type { FlowResult, KioskSession, SpeechPlan, TurnAnalysis } from "@/lib/types"

// Prefix for conversation items the application injects for the model's benefit rather than
// the customer's -- currently only the state summary pushed after a reconnect. Filtered out
// of the captions so it never appears on screen.
export const APPLICATION_EVENT_PREFIX = "[EVENTO_APLICACION]"

export interface ConversationCaption {
  id: string
  role: "user" | "assistant"
  text: string
  completed: boolean
}

export interface KioskRealtimeCallbacks {
  // Supplies the voice session's own transcription of the turn the model is calling about.
  // The model never types the transcript itself: it was observed corrupting it outright
  // ("reportar el robo" -> "portar el juego") and the backend classified the corruption.
  // Returns null when transcription has not landed, which is a retry, not a fallback.
  resolveSpokenText: () => Promise<string | null>
  analyzeRequirement: (transcript: string, callId?: string) => Promise<TurnAnalysis>
  confirmRequirement: (confirmed: boolean, callId?: string) => Promise<FlowResult>
}

export function kioskRouteForState(state: {
  session: KioskSession | null
  result: FlowResult | null
  analysis?: TurnAnalysis | null
}): string {
  if (!state.session) return "/kiosco"
  if (state.result?.next_action === "IDENTIFY") return "/kiosco/identificacion"
  if (state.result?.next_action === "COMPLETE") {
    return state.result.resolution_type === "AUTOMATIC"
      ? "/kiosco/respuesta"
      : "/kiosco/ticket"
  }
  if (state.analysis?.next_action === "DECLINE") return "/kiosco/respuesta"
  return "/kiosco/voz"
}

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim()
}

function foldForComparison(value: string): string {
  return compactText(value)
    .toLocaleLowerCase("es")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
}

function normalizeConfirmation(value: string): string {
  return foldForComparison(value)
}

// Bolivian Spanish answers a yes/no question with far more than "si": "claro", "asi es",
// "exacto", "por supuesto" and "ya" are all ordinary confirmations. Every one of them used to
// fall through to ASK_EXPLICIT_CONFIRMATION, so the kiosk re-asked a question the customer had
// already answered -- which reads as the kiosk not listening.
const NEGATIVE_CONFIRMATION =
  /\b(no|incorrecto|incorrecta|corregir|correccion|cambiar|equivocado|equivocada|negativo|tampoco|para nada|nada que ver|mas bien)\b/
const POSITIVE_CONFIRMATION =
  /\b(si|sip|correcto|correcta|confirmo|confirmar|de acuerdo|esta bien|es correcto|es correcta|claro|exacto|exactamente|asi es|asi mismo|eso es|por supuesto|obvio|dale|afirmativo|ya pues)\b/

const ADVERSATIVE_CONNECTOR = /\b(pero|aunque|sin embargo|en realidad|mejor dicho|espera)\b/

export function explicitConfirmation(value: string): boolean | null {
  const normalized = normalizeConfirmation(value)
  const negative = NEGATIVE_CONFIRMATION.test(normalized)
  const positive = POSITIVE_CONFIRMATION.test(normalized)

  if (positive !== negative) return positive
  if (!positive) return null

  // Both cues matched. "Si, pero no" really is a retraction and must keep re-asking, so an
  // adversative connector still means ambiguous. Without one, "Si, y ademas no reconozco un
  // cargo" is a confirmation followed by more detail, and the cue that comes first is the
  // answer -- re-asking there is the kiosk failing to hear a yes it was given.
  if (ADVERSATIVE_CONNECTOR.test(normalized)) return null
  const positiveIndex = normalized.search(POSITIVE_CONFIRMATION)
  const negativeIndex = normalized.search(NEGATIVE_CONFIRMATION)
  if (positiveIndex === negativeIndex) return null
  return positiveIndex < negativeIndex
}

export function captionsFromHistory(history: RealtimeItem[]): ConversationCaption[] {
  return history.flatMap((item): ConversationCaption[] => {
    if (item.type !== "message" || item.role === "system") return []

    const text = compactText(
      item.content
        .map((part) => {
          if (part.type === "input_text") return part.text
          if (part.type === "input_audio") return part.transcript ?? ""
          if (part.type === "output_text") return part.text
          if (part.type === "output_audio") return part.transcript ?? ""
          return ""
        })
        .filter(Boolean)
        .join(" "),
    )
    if (!text || text.startsWith(APPLICATION_EVENT_PREFIX)) return []

    return [
      {
        id: item.itemId,
        role: item.role,
        text,
        completed: item.status === "completed",
      },
    ]
  })
}

export interface TranscriptSelection {
  text: string
  itemIds: string[]
}

// The authoritative record of what the customer said is the voice session's own Spanish
// transcription. On 2026-08-19 a customer said "Quiero reportar el robo de mi tarjeta de
// debito"; the transcription got it right, the model typed "Quiero portar el juego de mi
// tarjeta de debito" into its tool call, and that is what reached the classifier. The tool
// no longer carries a transcript argument at all, so this is the only source there is.
//
// Multiple items are joined in history order: a single spoken turn can arrive split across two
// conversation items when the customer pauses mid-sentence.
export function selectAuthoritativeTranscript(
  captions: ConversationCaption[],
  consumed: ReadonlySet<string>,
): TranscriptSelection | null {
  const pending = captions.filter(
    (caption) => caption.role === "user" && caption.completed && !consumed.has(caption.id),
  )
  if (pending.length === 0) return null
  const text = compactText(pending.map((caption) => caption.text).join(" "))
  if (!text) return null
  return { text, itemIds: pending.map((caption) => caption.id) }
}

// Everything the model is given for a step: the facts, what to do with them, and the strings
// that must come out unchanged. `guidance` and `facts` are the model's raw material; only
// `verbatim` constrains the actual words.
export function speechPlanToolOutput(
  plan: SpeechPlan,
  extras: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ok: true,
    ...extras,
    intent: plan.intent,
    guidance: plan.guidance,
    facts: plan.facts ?? {},
    verbatim: plan.verbatim ?? [],
  }
}

export function analysisToolOutput(response: TurnAnalysis): Record<string, unknown> {
  // A confident GENERAL request resolves on this same turn (see turn_nodes.requires_confirmation
  // on the backend) and next_action is COMPLETE with the answer embedded in `result`. That is
  // exactly what confirmRequirement / submitIdentification report when they finish a flow, so
  // route it through the same shape rather than a second, differently-keyed one.
  if (response.next_action === "COMPLETE" && response.result) {
    return flowToolOutput(response.result)
  }
  return speechPlanToolOutput(response.speech_plan, {
    next_action: response.next_action,
    requirement_id: response.requirement_id,
  })
}

export function flowToolOutput(response: FlowResult): Record<string, unknown> {
  return speechPlanToolOutput(response.speech_plan, {
    next_action: response.next_action,
    requirement_id: response.requirement_id,
    resolution_type: response.resolution_type,
    identification_status: response.identification_status,
  })
}

export function errorToolOutput(guidance: string): Record<string, unknown> {
  return {
    ok: false,
    next_action: "RETRY",
    intent: "RETRY",
    guidance,
    facts: {},
    verbatim: [],
  }
}

// The one guard kept from the old controlled-speech machine, at a fraction of its size. It
// checks only what it can honestly check: text. Numbers deliberately never reach `verbatim`
// (see the note in orchestrator.py) because a model that says "el cuarenta y dos" instead of
// "42" has done nothing wrong, and a substring check would force a pointless re-read.
export function missingVerbatim(spoken: string, verbatim: readonly string[]): string[] {
  const haystack = foldForComparison(spoken)
  if (!haystack) return [...verbatim]
  return verbatim.filter((entry) => {
    const needle = foldForComparison(entry)
    return needle.length > 0 && !haystack.includes(needle)
  })
}

export function analysisSpeechPlan(response: TurnAnalysis): SpeechPlan {
  return response.result?.speech_plan ?? response.speech_plan
}

// A completed flow used to be the end of the session, full stop. It no longer is: a
// question the kiosk answered by itself leaves the customer standing there, and
// `cases.session_id` is no longer unique on the backend, so a second, unrelated question
// opens its own case in the same session. A human handoff still ends things -- from that
// point an executive owns the case -- and so does a declined request.
export function isTerminalFlowResult(result: {
  next_action: string
  resolution_type?: string | null
}): boolean {
  if (result.next_action !== "COMPLETE") return false
  return result.resolution_type !== "AUTOMATIC"
}

interface BusinessState {
  analysis: TurnAnalysis | null
  result: FlowResult | null
}

export function shouldApplyAnalysisResponse(
  state: BusinessState,
  response: TurnAnalysis,
  startingRequirementId: string | null,
  stateChanged: boolean,
): boolean {
  if (!stateChanged) return true
  if (state.analysis?.requirement_id === response.requirement_id) return false
  if (
    state.result?.next_action === "CAPTURE" &&
    state.result.requirement_id === response.requirement_id
  ) {
    return false
  }
  if (state.result && state.result.next_action !== "CAPTURE") return false
  if (
    state.analysis &&
    state.analysis.requirement_id !== startingRequirementId
  ) {
    return false
  }
  return true
}

function flowStage(result: FlowResult): number {
  return result.next_action === "COMPLETE" ? 2 : 1
}

export function shouldApplyFlowResponse(
  state: BusinessState,
  response: FlowResult,
  startingRequirementId: string,
  stateChanged: boolean,
): boolean {
  if (!stateChanged) return true
  if (state.result) {
    if (state.result.requirement_id !== response.requirement_id) {
      // A different requirement normally means a stale response arriving late. The one
      // exception is a follow-up: once an automatic answer has completed, the next question
      // is a genuinely new requirement and must replace it, not be discarded as stale.
      return !isTerminalFlowResult(state.result)
    }
    return flowStage(response) > flowStage(state.result)
  }
  if (state.analysis) {
    return state.analysis.requirement_id === startingRequirementId
  }
  return true
}
