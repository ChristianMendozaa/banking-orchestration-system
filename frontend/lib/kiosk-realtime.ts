import type { RealtimeItem, RealtimeSession } from "@openai/agents/realtime"

import type { FlowResult, KioskSession, TurnAnalysis } from "@/lib/types"

export const APPLICATION_EVENT_PREFIX = "[EVENTO_APLICACION]"
export const TRANSITION_METADATA_KEY = "transition_key"
export const MAX_CONTROLLED_SPEECH_REPLAYS = 1

export interface ConversationCaption {
  id: string
  role: "user" | "assistant"
  text: string
  completed: boolean
}

export interface KioskRealtimeCallbacks {
  // Replaces whatever the model typed with the voice session's own transcription of that
  // turn, when it has one. Both tools go through it: a mis-typed request is misrouted, and a
  // mis-typed "no" opens a case the customer just declined.
  resolveSpokenText: (fallback: string) => Promise<string>
  analyzeRequirement: (transcript: string, callId?: string) => Promise<TurnAnalysis>
  confirmRequirement: (confirmed: boolean, callId?: string) => Promise<FlowResult>
}

export interface ControlledTransition {
  transitionKey: string
  speechText: string
  nextAction: string
  terminal: boolean
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

export function requestControlledResponse(
  realtime: Pick<RealtimeSession, "transport">,
  instructions: string,
  transitionKey: string,
): void {
  const response = {
    instructions,
    tools: [],
    tool_choice: "none",
    metadata: { [TRANSITION_METADATA_KEY]: transitionKey },
  }
  if (realtime.transport.requestResponse) {
    realtime.transport.requestResponse(response)
    return
  }
  realtime.transport.sendEvent({ type: "response.create", response })
}

// `response.create` sends these as `response.instructions`, which *replaces* the session
// instructions for that response rather than adding to them. Every sentence the kiosk speaks
// goes through here, so leaving it at a bare "read this string" meant the Spanish persona
// configured on the session (openai_provider.create_realtime_client_secret) and on the agent
// applied to nothing the customer ever hears -- which is why the delivery read as flat and
// oddly accented. The exact-text constraint stays: these strings are business-critical.
export const CONTROLLED_SPEECH_PERSONA =
  "Eres la asistente virtual femenina de un kiosco bancario en Bolivia. Habla en español " +
  "boliviano natural, cordial y cálido, con ritmo de conversación y no de lectura."

export function controlledSpeechInstructions(speechText: string): string {
  return `${CONTROLLED_SPEECH_PERSONA} Pronuncia exactamente este mensaje, sin agregar, repetir ni reformular nada: ${JSON.stringify(
    compactText(speechText),
  )}`
}

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim()
}

function normalizeConfirmation(value: string): string {
  return compactText(value)
    .toLocaleLowerCase("es")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
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

// The realtime model used to *retype* what it thought it heard into the tool argument, and the
// backend classified that. On 2026-08-19 a customer said "Quiero reportar el robo de mi tarjeta
// de debito"; the session's own Whisper transcription got it right and it is what these
// captions carry, but the model typed "Quiero portar el juego de mi tarjeta de debito" and that
// is what reached the classifier. The transcription is the authoritative record of what was
// said, so it -- not the model's paraphrase -- is what gets classified.
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

function transcriptWords(value: string): string[] {
  return compactText(value)
    .toLocaleLowerCase("es")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/[^\p{Letter}\p{Number}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean)
}

// Word pairs, not single words. The corruption this exists to catch replaces the two words that
// carry the meaning while leaving the rest of the sentence intact -- "reportar el robo" became
// "portar el juego" -- which single-word overlap scores as 0.6 similar and shrugs at. Comparing
// adjacent pairs scores the same sentence at 0.33, because word order is what actually changed.
function transcriptShingles(value: string): Set<string> {
  const words = transcriptWords(value)
  if (words.length < 2) return new Set(words)
  return new Set(words.slice(0, -1).map((word, index) => `${word} ${words[index + 1]}`))
}

// Diagnostic only: a low token overlap between what was transcribed and what the model typed is
// the exact signature of the "portar el juego" corruption. Surfacing it makes the next
// occurrence visible instead of silently misrouting a case.
export const TRANSCRIPT_DIVERGENCE_THRESHOLD = 0.6

export function transcriptsDiverge(authoritative: string, modelSupplied: string): boolean {
  const left = transcriptShingles(authoritative)
  const right = transcriptShingles(modelSupplied)
  if (left.size === 0 || right.size === 0) return false
  let shared = 0
  for (const token of left) {
    if (right.has(token)) shared += 1
  }
  const union = left.size + right.size - shared
  return union > 0 && shared / union < TRANSCRIPT_DIVERGENCE_THRESHOLD
}

export function analysisTransitionKey(response: TurnAnalysis): string {
  return `${response.requirement_id}:${response.next_action}`
}

export function flowTransitionKey(response: FlowResult): string {
  if (response.next_action === "COMPLETE" && response.ticket) {
    return `ticket:${response.ticket.id}`
  }
  return `${response.requirement_id}:${response.next_action}`
}

interface BusinessState {
  analysis: TurnAnalysis | null
  result: FlowResult | null
}

export function businessTransitionKey(state: BusinessState): string | null {
  if (state.result) return flowTransitionKey(state.result)
  if (state.analysis) return analysisTransitionKey(state.analysis)
  return null
}

export function shouldReplayControlledTransition(
  state: BusinessState,
  transition: ControlledTransition,
  requestRevision: number,
  currentRevision: number,
): boolean {
  const currentTransitionKey = businessTransitionKey(state)
  if (currentTransitionKey) {
    return currentTransitionKey === transition.transitionKey
  }
  return (
    requestRevision === currentRevision &&
    ["WELCOME", "RETRY", "ASK_EXPLICIT_CONFIRMATION"].includes(
      transition.nextAction,
    )
  )
}

export function canReplayControlledSpeech(attempts: number): boolean {
  return attempts < MAX_CONTROLLED_SPEECH_REPLAYS
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

export function shouldApplyFlowResponse(
  state: BusinessState,
  response: FlowResult,
  startingRequirementId: string,
  stateChanged: boolean,
): boolean {
  if (!stateChanged) return true
  if (state.result) {
    if (flowTransitionKey(state.result) === flowTransitionKey(response)) return false
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

export function analysisToolOutput(response: TurnAnalysis): Record<string, unknown> {
  // A confident GENERAL request now resolves on this same turn (see
  // turn_nodes.requires_confirmation on the backend) and next_action is COMPLETE with the
  // answer embedded in `result`. That is exactly the shape confirmRequirement /
  // submitIdentification already report when they finish a flow, so route it through the
  // same tool-output shape and transition key (flowToolOutput / flowTransitionKey) instead
  // of a second, differently-keyed "analysis" transition for the same event.
  if (response.next_action === "COMPLETE" && response.result) {
    return flowToolOutput(response.result)
  }
  return {
    ok: true,
    requirement_id: response.requirement_id,
    next_action: response.next_action,
    speech_text: response.speech_text,
    transition_key: analysisTransitionKey(response),
    protected_summary: response.summary,
    customer_summary: response.customer_summary,
    category: response.category,
    priority: response.priority,
    consultation_level: response.consultation_level,
    clarification_question: response.clarification_question,
  }
}

export function flowToolOutput(response: FlowResult): Record<string, unknown> {
  return {
    ok: true,
    requirement_id: response.requirement_id,
    next_action: response.next_action,
    speech_text: response.speech_text,
    transition_key: flowTransitionKey(response),
    customer_summary: response.customer_summary,
    priority: response.priority,
    resolution_type: response.resolution_type,
    identification_status: response.identification_status,
    response: response.response,
    ticket: response.ticket,
    executive: response.executive,
  }
}

export function errorToolOutput(
  toolName: string,
  callId: string | undefined,
  speechText: string,
) {
  return {
    ok: false,
    next_action: "RETRY",
    speech_text: speechText,
    transition_key: `${toolName}:${callId ?? crypto.randomUUID()}:ERROR`,
  }
}

export function controlledTransitionFromToolResult(
  result: string,
): ControlledTransition | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(result)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== "object") return null

  const record = parsed as Record<string, unknown>
  if (
    typeof record.transition_key !== "string" ||
    typeof record.speech_text !== "string" ||
    typeof record.next_action !== "string"
  ) {
    return null
  }

  return {
    transitionKey: record.transition_key,
    speechText: compactText(record.speech_text),
    nextAction: record.next_action,
    terminal:
      record.next_action === "DECLINE" ||
      isTerminalFlowResult({
        next_action: record.next_action,
        resolution_type:
          typeof record.resolution_type === "string" ? record.resolution_type : null,
      }),
  }
}
