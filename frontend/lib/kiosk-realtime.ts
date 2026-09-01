import type { RealtimeItem } from "@openai/agents/realtime"

import { ApiError } from "@/lib/api"
import type { RealtimeAudioInput } from "@/lib/kiosk-api"
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
  createdAt?: string
}

// What a tool gets when it reads the turn. Reading is deliberately not the same as spending:
// a turn is only `commit`ted once a tool has actually acted on those words, so a tool that
// reads them and then declines to use them leaves them for the tool that should have.
export interface SpokenTurn {
  text: string
  commit: () => void
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

export interface KioskRealtimeCallbacks {
  // A business result the application already has and the model has not been told about.
  // The only one today is the outcome of submitting the identity-card number: that happens
  // on a form, not in speech, so there is no turn to process and the tool would otherwise
  // answer "nothing to do" -- leaving the ticket number, the window and the executive's
  // name in `facts` that never reached the model. Returning it here delivers the backend's
  // own SpeechPlan through the one channel business data is allowed to travel in.
  takePendingResult: () => KioskTurnProcessingResult | null
  // Supplies the voice session's own transcription of the turn the model is calling about.
  // The model never types the transcript itself: it was observed corrupting it outright
  // ("reportar el robo" -> "portar el juego") and the backend classified the corruption.
  // Returns null when transcription has not landed, which is a retry, not a fallback.
  resolveSpokenText: () => Promise<SpokenTurn | null>
  // The application, not the voice model, chooses the business endpoint from current state.
  processSpokenTurn: (
    transcript: string,
    callId?: string,
  ) => Promise<KioskTurnProcessingResult>
}

export type KioskTurnProcessingResult =
  | { kind: "analysis"; response: TurnAnalysis }
  | { kind: "flow"; response: FlowResult }
  | { kind: "retry"; guidance: string }
  | { kind: "close" }
  // The session is holding the credential window open. There is nothing to process and
  // nothing went wrong: the person is typing.
  | { kind: "awaiting_identification" }
  // The flow already finished. A tool call here is the model checking in, not a new turn.
  | { kind: "settled" }
  // No unspent turn to act on. Distinct from `retry`, which is a real failure to resolve
  // something the person did say.
  | { kind: "noop" }

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

export type RealtimeToolChoice = "none" | "auto" | "required"

// Tool choice used to be driven by raw VAD events: `required` on every
// `input_audio_buffer.speech_started`, `auto` again once a tool started. Any cough, any
// "aja" while a backend call was in flight, and any of the kiosk's own audio leaking back
// into the microphone armed `required` for the *next* response -- which was frequently the
// response that was supposed to speak the tool result. Forced to call `procesar_turno`
// again instead, the model found no unspent transcript and apologised to the customer for
// a failure that never happened.
//
// It is now derived from the two facts that actually decide it: whether the greeting has
// happened, and whether an unspent customer transcript is sitting there. `required` is
// exactly as strong a guarantee as before -- every turn the person actually spoke still
// has to go through the tool -- without being armed by noise.
export function realtimeToolChoiceForTurn(state: {
  greeted: boolean
  hasUnspentTranscript: boolean
  // A result waiting to be handed over is as binding as an unspoken turn: without it the
  // model is free to narrate the outcome of a form submission it was never shown.
  hasPendingResult?: boolean
}): RealtimeToolChoice {
  // There is no customer turn during the greeting, so tools are forbidden. With `auto`
  // here the model called `procesar_turno` before any transcription existed, producing a
  // false "repiteme tu pedido" immediately after session startup.
  if (!state.greeted) return "none"
  if (state.hasUnspentTranscript || state.hasPendingResult) return "required"
  return "auto"
}

export function realtimeVoiceSessionConfig(
  audioInput: RealtimeAudioInput,
  voice: string,
  toolChoice: RealtimeToolChoice,
) {
  return {
    outputModalities: ["audio"] as const,
    parallelToolCalls: false,
    toolChoice,
    // The transport fills omitted audio properties with SDK defaults on every update. Always
    // resend the backend-minted block while toggling tool choice so transcription and VAD do
    // not silently change halfway through a conversation.
    audio: {
      input: {
        noiseReduction: audioInput.noise_reduction,
        transcription: audioInput.transcription,
        turnDetection: audioInput.turn_detection,
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
// tarjeta de debito" into its tool call, and that is what reached the classifier. The tool
// no longer carries a transcript argument at all, so this is the only source there is.
//
// Multiple items are joined in history order: a single spoken turn can arrive split across two
// conversation items when the customer pauses mid-sentence.
export function selectAuthoritativeTranscript(
  captions: ConversationCaption[],
  // Widened from `ReadonlySet` so callers can pass a union of two sets without building a
  // third: tool choice asks "was this offered to the tool?" while the tool itself asks
  // "was this acted on?", and those are deliberately different questions.
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
  return speechPlanToolOutput(response.speech_plan, extras)
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

// A successful "there is nothing for you to do here" result. It has to be `ok: true`: the
// persona reads `ok: false` as a failure it must apologise for, and none of these are
// failures. Every one of them used to fall through to `errorToolOutput`, which is why a
// customer who had just been handed the CI field heard the kiosk say it could not reach the
// system and ask them to try again.
function idleToolOutput(intent: string, guidance: string): Record<string, unknown> {
  return { ok: true, next_action: "NONE", intent, guidance, facts: {}, verbatim: [] }
}

export function turnProcessingToolOutput(
  result: KioskTurnProcessingResult,
): Record<string, unknown> {
  if (result.kind === "analysis") return analysisToolOutput(result.response)
  if (result.kind === "flow") return flowToolOutput(result.response)
  if (result.kind === "retry") return errorToolOutput(result.guidance)
  if (result.kind === "noop") {
    return idleToolOutput(
      "NOOP",
      "No hay nada nuevo que procesar en este momento. Sigue la conversación con " +
        "naturalidad: no te disculpes, no digas que tuviste un problema y no le pidas " +
        "que repita lo que ya dijo.",
    )
  }
  if (result.kind === "awaiting_identification") {
    return idleToolOutput(
      "IDENTIFY",
      "Está escribiendo su CI en el campo protegido de la pantalla. Espera en silencio: " +
        "no preguntes nada, no repitas la instrucción y no te disculpes.",
    )
  }
  if (result.kind === "settled") {
    return idleToolOutput(
      "SETTLED",
      "Esta atención ya quedó resuelta y se lo dijiste. No agregues nada nuevo ni " +
        "vuelvas a preguntar.",
    )
  }
  return {
    ok: true,
    next_action: "CLOSE",
    intent: "CLOSE",
    guidance: "Despídete brevemente y no hagas otra pregunta.",
    facts: {},
    verbatim: [],
  }
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
// nothing should be captured while someone types their CI -- and a terminal or declined
// result means the kiosk has said its last word on this case. Everywhere else, including
// while a tool runs, the mic stays live so the customer can interrupt, correct or add
// something.
export function microphoneShouldBeOpen(state: BusinessState): boolean {
  if (state.result?.next_action === "IDENTIFY") return false
  if (state.result && isTerminalFlowResult(state.result)) return false
  if (state.analysis?.next_action === "DECLINE") return false
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

// The kiosk has two things that can decide to speak: the realtime model, whose server-side
// VAD creates a response the moment the customer stops talking, and this application, which
// occasionally has to tell the model something happened on screen. Nothing used to arbitrate
// between them. The Agents SDK's own sequencer *queues* a `response.create` that arrives
// during an active response rather than dropping it, so every extra injection eventually
// came out of the speaker as a stray sentence trailing the previous one -- which is exactly
// what "it says several things at once" was.
//
// `SpeechFloor` is that arbiter. The floor is busy while a response is being generated or a
// tool call is running; an injection made while it is busy is held, coalesced last-wins per
// kind, and re-derived at the moment it is released so a request whose business state has
// moved on is dropped instead of spoken late.
export type SpeechFloorKind = "resume" | "identification_close"

export interface SpeechFloorTransport {
  // Adds a context item and lets the model reply to it under the full session persona.
  sendMessage: (text: string) => void
  // Cancels whatever is being said and clears the audio already buffered for playback.
  interrupt: () => void
}

// Re-derived at flush time, not at request time. Returning null withdraws the request.
export type SpeechFloorMessage = () => string | null

export class SpeechFloor {
  #transport: SpeechFloorTransport
  #responseActive = false
  // Generation finishing is not the same as the kiosk falling silent: `response.done`
  // arrives while the audio it produced is still coming out of the buffer. Both have to be
  // over before anything else takes the floor, or the session gets torn down -- or spoken
  // over -- mid-sentence.
  #playbackActive = false
  #activeTools = 0
  #pending = new Map<SpeechFloorKind, SpeechFloorMessage>()
  #waiters: (() => void)[] = []

  constructor(transport: SpeechFloorTransport) {
    this.#transport = transport
  }

  get busy(): boolean {
    return this.#responseActive || this.#playbackActive || this.#activeTools > 0
  }

  noteResponseStarted(): void {
    this.#responseActive = true
  }

  noteResponseDone(): void {
    this.#responseActive = false
    this.#release()
  }

  noteAudioStarted(): void {
    this.#playbackActive = true
  }

  /**
   * Playback ended -- finished, cleared, or cut short by the customer talking over it.
   * Every one of those has to land here: a floor left believing audio is still playing
   * would hold a pending message, and the session open, forever.
   */
  noteAudioFinished(): void {
    this.#playbackActive = false
    this.#release()
  }

  noteToolStarted(): void {
    this.#activeTools += 1
  }

  noteToolFinished(): void {
    this.#activeTools = Math.max(0, this.#activeTools - 1)
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
   */
  preempt(kind: SpeechFloorKind, message: SpeechFloorMessage): void {
    if (this.#responseActive || this.#playbackActive) {
      try {
        this.#transport.interrupt()
      } catch {
        // Nothing was playing, or the transport is already gone. Either way the message
        // below is still the right thing to say next.
      }
      // `response.done` and the cleared audio buffer follow a cancellation and would clear
      // these anyway; doing it here lets the message go out on this tick rather than
      // waiting for the round trip.
      this.#responseActive = false
      this.#playbackActive = false
    }
    this.request(kind, message)
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
    this.#responseActive = false
    this.#playbackActive = false
    this.#activeTools = 0
    this.#pending.clear()
    const waiters = this.#waiters
    this.#waiters = []
    waiters.forEach((waiter) => waiter())
  }

  #release(): void {
    if (this.busy) return
    for (const [kind, message] of [...this.#pending]) {
      this.#pending.delete(kind)
      const text = message()
      if (!text) continue
      try {
        this.#transport.sendMessage(text)
        // One injection at a time: it has just started a response, and whatever is still
        // queued gets its turn when that one is done.
        this.#responseActive = true
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
