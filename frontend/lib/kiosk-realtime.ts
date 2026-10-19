import type { RealtimeItem } from "@openai/agents/realtime"

import { ApiError } from "@/lib/api"
import type { RealtimeAudioInput } from "@/lib/kiosk-api"
import type { FlowResult, KioskSession, SpeechPlan, TurnAnalysis } from "@/lib/types"

export interface ConversationCaption {
  id: string
  role: "user" | "assistant"
  text: string
  completed: boolean
  createdAt?: string
}

// Backend codes that mean "this client and the session disagree about where the
// conversation is", not "the bank is unreachable". `POST /turns` is rejected with
// INVALID_SESSION_STATE for the whole time the credential window is open, and every one of
// these used to reach the customer as an apology about not being able to consult the
// system. They are races this client resolves by reconciling, silently.
const SESSION_STATE_CONFLICT_CODES = new Set([
  "INVALID_SESSION_STATE",
  "INVALID_CLARIFICATION",
  "TURN_ALREADY_COMPLETED",
])

export function isSessionStateConflict(reason: unknown): boolean {
  return reason instanceof ApiError && SESSION_STATE_CONFLICT_CODES.has(reason.code)
}

export function isSessionExhausted(reason: unknown): boolean {
  return reason instanceof ApiError && reason.code === "SESSION_TURN_LIMIT_REACHED"
}

// Realtime `error` events that describe a lost race for the response slot rather than a
// broken session. The transport queues a `response.create` behind whatever is speaking and
// cancels the current response on barge-in; both can be answered with one of these, and
// showing the customer a "reconnect the conversation" banner over it is wrong.
const BENIGN_REALTIME_ERROR_CODES = new Set([
  "conversation_already_has_active_response",
  "response_cancel_not_active",
])

export function isBenignRealtimeError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false
  const payload = error as { code?: unknown; error?: { code?: unknown } }
  const code = payload.error?.code ?? payload.code
  return typeof code === "string" && BENIGN_REALTIME_ERROR_CODES.has(code)
}

// Results the kiosk has nothing to add to. Silence here is not a preference: the person is
// typing their identity card, or the case is closed, or the answer that came back is stale,
// or this client and the session disagreed about where the conversation is and are
// reconciling. None of them gets a response at all -- the application asks for every
// response itself, so silence is simply not asking.
export function turnResultIsSilent(result: KioskTurnProcessingResult): boolean {
  return (
    result.kind === "awaiting_identification" ||
    result.kind === "settled" ||
    result.kind === "superseded" ||
    result.kind === "noop"
  )
}

export type KioskTurnProcessingResult =
  | { kind: "analysis"; response: TurnAnalysis }
  | { kind: "flow"; response: FlowResult }
  | { kind: "retry"; guidance: string }
  | { kind: "close" }
  // The session is holding the credential window open. There is nothing to process and
  // nothing went wrong: the person is typing.
  | { kind: "awaiting_identification" }
  // The flow already finished; there is nothing left to say about it.
  | { kind: "settled" }
  // The backend and this client disagreed about the session's state. Reconciliation is
  // under way and nothing went wrong that the customer needs to hear about. Distinct from
  // `retry`, which is a real failure to resolve something the person did say.
  | { kind: "noop" }
  // The backend answered, but the conversation moved on while it was answering. The answer
  // is real and simply no longer current; it is kept for reconciliation and must not be
  // spoken. Returning the response itself here is what let obsolete answers reach the
  // speaker even after the client had refused to show them.
  | { kind: "superseded" }

export function kioskRouteForState(state: {
  session: KioskSession | null
  result: FlowResult | null
  analysis?: TurnAnalysis | null
}): string {
  if (!state.session) return "/kiosco"
  if (state.result?.next_action === "IDENTIFY") return "/kiosco/identificacion"
  if (state.result?.next_action === "COMPLETE") {
    return state.result.resolution_type === "AUTOMATIC"
      ? "/kiosco/voz"
      : "/kiosco/ticket"
  }
  if (isTerminalDecline(state.analysis)) return "/kiosco/respuesta"
  return "/kiosco/voz"
}

// A decline used to end the session outright, and the turn it declined was as often a
// bystander's sentence as the customer's request. The backend now keeps listening after one
// and says so in `conversation_can_continue`; only a run of them in a row is the end.
export function isTerminalDecline(analysis: TurnAnalysis | null | undefined): boolean {
  return analysis?.next_action === "DECLINE" && !analysis.conversation_can_continue
}

export function declineCanContinue(analysis: TurnAnalysis | null | undefined): boolean {
  return analysis?.next_action === "DECLINE" && Boolean(analysis.conversation_can_continue)
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
// Deliberately without a bare `si`. Stripping diacritics collapses the affirmation "sí" onto
// the conditional conjunction "si", and "si no es correcto, corrígelo" then matched positive
// at index 0 and negative at index 3 -- a banking requirement confirmed by a sentence
// questioning it. The accent is the distinction, so it is read before folding.
const POSITIVE_CONFIRMATION =
  /\b(sip|correcto|correcta|confirmo|confirmar|de acuerdo|esta bien|es correcto|es correcta|claro|exacto|exactamente|asi es|asi mismo|eso es|por supuesto|obvio|dale|afirmativo|ya pues)\b/
// The accented affirmation on text that has not been folded. `\b` is ASCII-only in JavaScript
// and does not see a boundary after "í", so the edges are spelled out as "not a letter".
const ACCENTED_YES = /(?<!\p{L})sí(?!\p{L})/u
// A transcription that dropped the accent is only unambiguous when the reply is nothing else.
const BARE_YES = /^(?:si|sip)$/

const ADVERSATIVE_CONNECTOR = /\b(pero|aunque|sin embargo|en realidad|mejor dicho|espera)\b/
// A reply short enough that the cue is the whole of it. "Sí", "no, es incorrecto" and "así
// es" carry nothing but the answer; past that the extra words are usually the interesting
// part -- "no, quería consultar los requisitos" is a rejection that already said what it
// wanted instead, and settling it here would throw that away. Mirrors
// `MAX_SETTLED_WORDS` in backend/app/services/agents/rules/confirmation.py.
const MAX_SETTLED_WORDS = 4

/**
 * A shortcut for replies that cannot mean anything else -- not the decision itself. What it
 * returns travels to the backend alongside the words that produced it, because "sí, pero
 * quiero consultar primero" and "claro, ¿qué entendiste?" are not questions a cue list in a
 * browser can answer.
 */
export function explicitConfirmation(value: string): boolean | null {
  const spoken = compactText(value).toLocaleLowerCase("es")
  const normalized = normalizeConfirmation(value)
  // Someone answering a yes/no question with a question of their own has not answered it.
  // "Claro, ¿qué entendiste?" matched `claro` and confirmed a banking requirement.
  if (/[?¿]/.test(spoken)) return null
  // "Sí, pero quiero consultar primero" is a yes to a different question: an adversative
  // connector qualifies whatever cue precedes it, and a cue table cannot tell how.
  if (ADVERSATIVE_CONNECTOR.test(normalized)) return null
  if (normalized.split(" ").filter(Boolean).length > MAX_SETTLED_WORDS) return null

  const accentedYes = ACCENTED_YES.test(spoken) || BARE_YES.test(normalized)
  const negative = NEGATIVE_CONFIRMATION.test(normalized)
  const positive = accentedYes || POSITIVE_CONFIRMATION.test(normalized)

  if (positive !== negative) return positive
  // Neither cue fired, or both did -- "sí, y además no reconozco un cargo" is a yes carrying
  // a second, unrelated concern that must not be swallowed by the yes. Both are exactly the
  // shapes the backend reads rather than matches.
  return null
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
    if (!text) return []

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

export interface StoredConversationMessage {
  item_id: string
  role: "CUSTOMER" | "ASSISTANT"
  text: string
  created_at: string
}

export function captionsFromStoredConversation(
  messages: StoredConversationMessage[],
): ConversationCaption[] {
  return messages.map((message) => ({
    id: message.item_id,
    role: message.role === "CUSTOMER" ? "user" : "assistant",
    text: compactText(message.text),
    completed: true,
    createdAt: message.created_at,
  }))
}

// Realtime history is connection-local; persisted history spans reconnects. Keep the base
// order, replace matching entries with their fresher live version, and append truly new items.
export function mergeConversationCaptions(
  base: ConversationCaption[],
  incoming: ConversationCaption[],
): ConversationCaption[] {
  const incomingById = new Map(incoming.map((caption) => [caption.id, caption]))
  const merged = base.map((caption) => incomingById.get(caption.id) ?? caption)
  const seen = new Set(base.map((caption) => caption.id))
  for (const caption of incoming) {
    if (!seen.has(caption.id)) {
      merged.push(caption)
      seen.add(caption.id)
    }
  }
  return merged
}

export function isConversationClose(value: string): boolean {
  const normalized = foldForComparison(value).replace(/[.!?]+$/g, "")
  return /^(?:no\s*,?\s*)?(?:gracias|nada mas|eso es todo|seria todo|no necesito nada mas|listo)(?:\s*,?\s*gracias)?$/.test(
    normalized,
  )
}

// Realtime server events name the response they belong to in one of two places depending on
// the event: `response.created`/`response.done` nest it under `response`, the output audio
// buffer events carry a flat `response_id`. Reading it is what lets the floor tell a late
// event from a current one -- see `SpeechFloor`.
export function realtimeResponseId(event: unknown): string | undefined {
  if (!event || typeof event !== "object") return undefined
  const payload = event as { response_id?: unknown; response?: { id?: unknown } }
  if (typeof payload.response_id === "string") return payload.response_id
  if (typeof payload.response?.id === "string") return payload.response.id
  return undefined
}

// The session never decides to answer by itself (`create_response` is off, see
// backend/app/services/openai_provider.py), so the only thing left to toggle is whether the
// customer's voice may cut the kiosk off. It may, except during the greeting: on
// 2026-10-14 the people standing around the kiosk talked over it the moment it connected.
export function realtimeVoiceSessionConfig(
  audioInput: RealtimeAudioInput,
  voice: string,
  options: { interruptResponse: boolean },
) {
  return {
    outputModalities: ["audio" as const],
    // The transport fills omitted audio properties with SDK defaults on every update. Always
    // resend the backend-minted block so transcription and VAD do not silently change
    // halfway through a conversation. The SDK reads the camelCase key ahead of the
    // snake_case one the backend sent, which is what lets this override it.
    audio: {
      input: {
        noiseReduction: audioInput.noise_reduction,
        transcription: audioInput.transcription,
        turnDetection: {
          ...audioInput.turn_detection,
          interruptResponse: options.interruptResponse,
        },
      },
      output: { voice },
    },
  }
}

export interface TranscriptSelection {
  text: string
  itemIds: string[]
}

// The authoritative record of what the customer said is the voice session's own Spanish
// transcription. On 2026-08-19 a customer said "Quiero reportar el robo de mi tarjeta de
// debito"; the transcription got it right, the model typed "Quiero portar el juego de mi
// tarjeta de debito" into its tool call, and that is what reached the classifier. The model
// is no longer asked to carry the customer's words anywhere, so this is the only source.
//
// Multiple items are joined in history order: a single spoken turn can arrive split across two
// conversation items when the customer pauses mid-sentence.
export function selectAuthoritativeTranscript(
  captions: ConversationCaption[],
  consumed: { has: (itemId: string) => boolean },
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
export function speechPlanData(
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

export function analysisSpeechData(response: TurnAnalysis): Record<string, unknown> {
  // A confident GENERAL request resolves on this same turn (see turn_nodes.requires_confirmation
  // on the backend) and next_action is COMPLETE with the answer embedded in `result`. That is
  // exactly what confirmRequirement / submitIdentification report when they finish a flow, so
  // route it through the same shape rather than a second, differently-keyed one.
  if (response.next_action === "COMPLETE" && response.result) {
    return flowSpeechData(response.result)
  }
  return speechPlanData(response.speech_plan, {
    next_action: response.next_action,
    requirement_id: response.requirement_id,
  })
}

export function flowSpeechData(response: FlowResult): Record<string, unknown> {
  const extras: Record<string, unknown> = {
    next_action: response.next_action,
    requirement_id: response.requirement_id,
    resolution_type: response.resolution_type,
    identification_status: response.identification_status,
  }
  if (response.resolution_type === "AUTOMATIC" && response.response) {
    // Do not make the voice model infer that a long `verbatim` entry is the actual bank
    // answer. This top-level field makes the successful grounding result unmistakable.
    extras.grounded_answer = response.response
  }
  return speechPlanData(response.speech_plan, extras)
}

// What the kiosk says when the bank could not be reached. `ok: false` is reserved for this:
// a state the session is reconciling is `noop`, and silent.
export const OUTAGE_GUIDANCE =
  "No pudiste consultar el sistema. Discúlpate brevemente y dile que lo intente otra vez o " +
  "que pida ayuda a un ejecutivo."

export function retrySpeechData(guidance: string): Record<string, unknown> {
  return {
    ok: false,
    next_action: "RETRY",
    intent: "RETRY",
    guidance,
    facts: {},
    verbatim: [],
  }
}

/** What there is to say about a turn, or null when the kiosk says nothing at all. */
export function turnSpeechData(
  result: KioskTurnProcessingResult,
): Record<string, unknown> | null {
  if (turnResultIsSilent(result)) return null
  if (result.kind === "analysis") return analysisSpeechData(result.response)
  if (result.kind === "flow") return flowSpeechData(result.response)
  if (result.kind === "retry") return retrySpeechData(result.guidance || OUTAGE_GUIDANCE)
  return {
    ok: true,
    next_action: "CLOSE",
    intent: "CLOSE",
    guidance: "Despídete brevemente y no hagas otra pregunta.",
    facts: {},
    verbatim: [],
  }
}

// Every response the kiosk gives is asked for by the application, with the session persona
// followed by what this one turn is about. A `response.create` that carries `instructions`
// replaces the session's for that response, which is why the persona is repeated in full
// rather than referred to. The persona itself (backend/app/services/prompts/voice.py) tells
// the model to look for this heading and to treat it as everything it knows about the case.
function withTurn(persona: string, turn: string): string {
  return `${persona}\n\nESTE TURNO\n${turn}`
}

const TURN_DATA_RULES = [
  "La aplicación ya procesó lo que dijo la persona. Abajo está el resultado, en datos.",
  "- Haz lo que dice `guidance`.",
  "- Usa solo los datos de `facts`; no agregues ninguno.",
  "- Di cada texto de `verbatim` palabra por palabra. Puedes presentarlo y cerrarlo con " +
    "tus palabras, pero por dentro va tal cual.",
  "- Si `ok` es true, el resultado es autoritativo: nunca digas que no tienes un dato " +
    "que está ahí.",
  "- No menciones estos datos, la aplicación ni cómo funcionas.",
].join("\n")

/** The instructions for speaking a turn's outcome, or null when it has nothing to say. */
export function turnInstructions(
  persona: string,
  result: KioskTurnProcessingResult,
): string | null {
  const data = turnSpeechData(result)
  if (!data) return null
  return withTurn(persona, `${TURN_DATA_RULES}\n\n${JSON.stringify(data)}`)
}

export function greetingInstructions(persona: string): string {
  return withTurn(
    persona,
    "Recién empieza la atención. Preséntate en una frase y pregunta en qué puedes ayudar. " +
      "Si nombras lo que atiendes, nombra solo lo de LO QUE ATIENDES.",
  )
}

// Said only when the bank takes long enough that silence starts to sound like the kiosk did
// not hear. Fixed on purpose: the model's own fillers were "Claro, déjame verificar la
// petición por un momento" before every single lookup, including the fast ones.
export function fillerInstructions(persona: string): string {
  return withTurn(
    persona,
    'La consulta todavía está en proceso. Di solamente: "Un momento, por favor." ' +
      "No digas nada más.",
  )
}

/** A situation the model has to speak to that is not a turn's outcome, such as a reconnect. */
export function situationInstructions(persona: string, situation: string): string {
  return withTurn(persona, situation)
}

// A single word that is neither a yes/no nor a goodbye is almost always the front of a
// sentence the person has not finished: "Quiero...", "Eh...". On 2026-10-14 a lone "Quiero"
// was sent to the bank as a whole request. The caller holds such a fragment for a moment so
// the rest can join it -- and sends it anyway if nothing follows, because the person's words
// are never dropped.
export function isSpeechFragment(value: string): boolean {
  const words = foldForComparison(value)
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(" ")
    .filter(Boolean)
  if (words.length !== 1) return false
  return explicitConfirmation(value) === null && !isConversationClose(value)
}

// The one guard kept from the old controlled-speech machine, at a fraction of its size, and
// now purely an observation: a miss puts a note on screen, it never sends the model back to
// re-read anything. Correcting speech by injecting a new message was how the kiosk ended up
// emitting stray fragments after the ticket number.
//
// It measures only what a text comparison can settle. Speech renders digits as words --
// "Ventanilla 3" is heard as "ventanilla tres" and "42" as "cuarenta y dos" -- so an entry
// carrying a digit would fail on a perfectly correct reading. Those are skipped rather than
// flagged; the backend keeps operational numbers out of `verbatim` in the first place
// (see the module docstring in backend/app/services/orchestrator/speech.py), and the one
// long digit-bearing entry that remains by design is the grounded answer, whose full text
// is on screen either way.
export function isMeasurableVerbatim(entry: string): boolean {
  return entry.length > 0 && !/\d/.test(entry)
}

export function missingVerbatim(spoken: string, verbatim: readonly string[]): string[] {
  const measurable = verbatim.filter(isMeasurableVerbatim)
  const haystack = foldForComparison(spoken)
  if (!haystack) return [...measurable]
  return measurable.filter((entry) => {
    const needle = foldForComparison(entry)
    return needle.length > 0 && !haystack.includes(needle)
  })
}

/**
 * The request a rejection named in place of the one it rejected, when there was one.
 *
 * Read defensively rather than off the generated type so a client running against an older
 * backend simply sees no correction instead of failing.
 */
export function correctedRequest(response: FlowResult): string | null {
  if (response.next_action !== "CAPTURE") return null
  const value = (response as { corrected_request?: unknown }).corrected_request
  return typeof value === "string" && value.trim() ? value.trim() : null
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
  conversation_can_continue?: boolean
}): boolean {
  if (result.next_action !== "COMPLETE") return false
  if (typeof result.conversation_can_continue === "boolean") {
    return !result.conversation_can_continue
  }
  return result.resolution_type !== "AUTOMATIC"
}

interface BusinessState {
  analysis: TurnAnalysis | null
  result: FlowResult | null
}

// The only three states that close the microphone. IDENTIFY is a credential window --
// nothing should be captured while someone types their CI -- and a terminal result or a
// terminal decline means the kiosk has said its last word on this case. Everywhere else,
// including while the bank is answering, the mic stays live so the customer can interrupt,
// correct or add something.
export function microphoneShouldBeOpen(state: BusinessState): boolean {
  if (state.result?.next_action === "IDENTIFY") return false
  if (state.result && isTerminalFlowResult(state.result)) return false
  if (isTerminalDecline(state.analysis)) return false
  return true
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

// Only the application asks the kiosk to speak -- the session's own turn detection no longer
// creates responses -- but it asks from several places at once: a turn's outcome, the filler
// while the bank is slow, the greeting, a reconnect, the identity-card closing. The Agents
// SDK's sequencer *queues* a `response.create` that arrives during an active response rather
// than dropping it, so without an arbiter every extra request eventually came out of the
// speaker as a stray sentence trailing the previous one -- and on 2026-10-14 the greeting
// came out *last*, behind two answers to the noise in the room.
//
// `SpeechFloor` is that arbiter. The floor is busy while a response is being generated or
// played; a request made while it is busy is held, coalesced last-wins per kind, and
// re-derived at the moment it is released so a request whose business state has moved on is
// dropped instead of spoken late.
export type SpeechFloorKind = "greeting" | "turn" | "filler" | "resume" | "identification_close"

export interface SpeechFloorTransport {
  // Asks the model for one response under these instructions, with tools forbidden.
  speak: (instructions: string) => void
  // Cancels whatever is being said and clears the audio already buffered for playback.
  interrupt: () => void
}

// Re-derived at flush time, not at request time. Returning null withdraws the request.
export type SpeechFloorMessage = () => string | null

// Responses are identified because the events that end one arrive *after* the event that
// starts the next. A floor that only counted "is something speaking" freed the replacement
// response the moment the cancelled one reported `response.done`.
const UNCORRELATED_RESPONSE = "__uncorrelated__"

// How long the floor waits for the server to acknowledge a `response.create` it asked for.
// Without a ceiling, a rejected injection (`conversation_already_has_active_response`, which
// the provider deliberately swallows) would leave the floor busy for the rest of the session.
const RESPONSE_CREATE_GRACE_MS = 4_000

interface FloorResponse {
  generating: boolean
  playing: boolean
  // Cancelled responses still emit `response.done` and `output_audio_buffer.cleared`. They
  // are tracked to completion so the bookkeeping stays balanced, but nothing waits on them.
  cancelled: boolean
}

export class SpeechFloor {
  #transport: SpeechFloorTransport
  // Generation finishing is not the same as the kiosk falling silent: `response.done`
  // arrives while the audio it produced is still coming out of the buffer. An entry lives
  // until both are over.
  #responses = new Map<string, FloorResponse>()
  // A `response.create` this floor put on the wire whose `response.created` has not come
  // back yet. The floor must look busy in that window or the next request overtakes it.
  #awaitingCreate = 0
  #createGraceTimers = new Set<ReturnType<typeof setTimeout>>()
  #pending = new Map<SpeechFloorKind, SpeechFloorMessage>()
  #waiters: (() => void)[] = []
  // Set by `silenceNow`: the next response to start belongs to the state that was just
  // invalidated -- a `response.create` already on the wire -- and is cancelled on arrival.
  #suppressNextResponse = false

  constructor(transport: SpeechFloorTransport) {
    this.#transport = transport
  }

  get busy(): boolean {
    if (this.#awaitingCreate > 0) return true
    for (const response of this.#responses.values()) {
      if (!response.cancelled && (response.generating || response.playing)) return true
    }
    return false
  }

  #entry(responseId: string | undefined): [string, FloorResponse] {
    const key = responseId ?? UNCORRELATED_RESPONSE
    let response = this.#responses.get(key)
    if (!response) {
      response = { generating: false, playing: false, cancelled: false }
      this.#responses.set(key, response)
    }
    return [key, response]
  }

  #forget(key: string, response: FloorResponse): void {
    if (!response.generating && !response.playing) this.#responses.delete(key)
  }

  noteResponseStarted(responseId?: string): void {
    this.#settleAwaitingCreate()
    const [key, response] = this.#entry(responseId)
    response.generating = true
    if (this.#suppressNextResponse) {
      this.#suppressNextResponse = false
      response.cancelled = true
      this.#cancel()
    }
    this.#responses.set(key, response)
  }

  noteResponseDone(responseId?: string): void {
    const key = responseId ?? UNCORRELATED_RESPONSE
    const response = this.#responses.get(key)
    // A `done` for a response this floor never saw start belongs to a connection or a turn
    // that is already over. Ignoring it is the whole point of correlating.
    if (!response) return
    response.generating = false
    this.#forget(key, response)
    this.#release()
  }

  noteAudioStarted(responseId?: string): void {
    const [key, response] = this.#entry(responseId)
    response.playing = true
    this.#responses.set(key, response)
  }

  /**
   * Playback ended -- finished, cleared, or cut short by the customer talking over it.
   * Every one of those has to land here: a floor left believing audio is still playing
   * would hold a pending message, and the session open, forever.
   *
   * Called without an id by the barge-in path, which reports that the speaker stopped
   * without saying whose audio it was. That silences every tracked response, which is
   * correct: the speaker is one device.
   */
  noteAudioFinished(responseId?: string): void {
    if (responseId === undefined) {
      for (const [key, response] of [...this.#responses]) {
        response.playing = false
        this.#forget(key, response)
      }
      this.#release()
      return
    }
    const response = this.#responses.get(responseId)
    if (!response) return
    response.playing = false
    this.#forget(responseId, response)
    this.#release()
  }

  /** Speak this as soon as the floor is free, or drop it if it has gone stale by then. */
  request(kind: SpeechFloorKind, message: SpeechFloorMessage): void {
    this.#pending.set(kind, message)
    if (!this.busy) this.#release()
  }

  /**
   * Take the floor for something that supersedes what is being said. Used when the customer
   * finishes typing their CI while the kiosk is still reading out the instruction to type
   * it: that sentence is now obsolete, and letting it run to completion before the closing
   * is what made a fast typist hear two unrelated turns back to back.
   *
   * Unlike the version this replaced, it does not assume the cancellation took effect. The
   * cancelled response is marked and its real `response.done` is awaited, which is what
   * stops its late events from freeing the message queued behind it.
   */
  preempt(kind: SpeechFloorKind, message: SpeechFloorMessage): void {
    this.silenceNow()
    this.request(kind, message)
  }

  /**
   * Cancel whatever is being said and queue nothing. Separate from `preempt` because the
   * identity-card submission has to silence the instruction it invalidates *before* the
   * HTTP round trip, and only knows what to say afterwards.
   */
  silenceNow(): void {
    let speaking = false
    for (const response of this.#responses.values()) {
      if (response.cancelled) continue
      if (response.generating || response.playing) {
        response.cancelled = true
        speaking = true
      }
    }
    // Whatever the transport is about to say about the state just invalidated must not be
    // heard either. The instruction to type the identity card can still be a
    // `response.create` on the wire when the card arrives, so cancelling only what is
    // already playing lets the obsolete sentence start *after* the thing that obsoleted it. The flag is cleared by
    // `#release`, so an injection the application deliberately makes is never caught by it.
    this.#suppressNextResponse = true
    if (speaking) this.#cancel()
  }

  /** Cancel a standing suppression, for a path that decided it has something to say. */
  allowNextResponse(): void {
    this.#suppressNextResponse = false
  }

  /** Run once the model has finished speaking -- or immediately, if it is not. */
  whenFree(callback: () => void): void {
    if (!this.busy && this.#pending.size === 0) {
      callback()
      return
    }
    this.#waiters.push(callback)
  }

  /** A closed session owes nobody a turn; release every waiter so timers still fire. */
  reset(): void {
    this.#responses.clear()
    this.#suppressNextResponse = false
    this.#settleAwaitingCreate()
    this.#pending.clear()
    const waiters = this.#waiters
    this.#waiters = []
    waiters.forEach((waiter) => waiter())
  }

  #cancel(): void {
    try {
      this.#transport.interrupt()
    } catch {
      // Nothing was playing, or the transport is already gone. Either way the caller's
      // intent -- that this must not be heard -- is unchanged.
    }
  }

  #settleAwaitingCreate(): void {
    this.#awaitingCreate = 0
    this.#createGraceTimers.forEach((timer) => clearTimeout(timer))
    this.#createGraceTimers.clear()
  }

  #release(): void {
    if (this.busy) return
    for (const [kind, message] of [...this.#pending]) {
      this.#pending.delete(kind)
      const text = message()
      if (!text) continue
      try {
        // The application is asking for this one on purpose; a suppression left standing
        // from an earlier `silenceNow` is about the sentence that was cancelled, not this.
        this.#suppressNextResponse = false
        this.#transport.speak(text)
        // One injection at a time. The floor is busy until the server acknowledges with
        // `response.created`; if it never does -- a rejected slot request -- the grace timer
        // frees it rather than wedging the session.
        this.#awaitingCreate += 1
        const timer = setTimeout(() => {
          this.#createGraceTimers.delete(timer)
          this.#awaitingCreate = Math.max(0, this.#awaitingCreate - 1)
          this.#release()
        }, RESPONSE_CREATE_GRACE_MS)
        this.#createGraceTimers.add(timer)
        return
      } catch {
        // The transport went away mid-flush. Remaining requests are dropped with it.
      }
    }
    const waiters = this.#waiters
    this.#waiters = []
    waiters.forEach((waiter) => waiter())
  }
}
