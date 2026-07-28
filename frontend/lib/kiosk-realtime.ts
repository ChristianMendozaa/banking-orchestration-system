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
}): string {
  if (!state.session) return "/kiosco"
  if (state.result?.next_action === "IDENTIFY") return "/kiosco/identificacion"
  if (state.result?.next_action === "COMPLETE") {
    return state.result.resolution_type === "AUTOMATIC"
      ? "/kiosco/respuesta"
      : "/kiosco/ticket"
  }
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

export function controlledSpeechInstructions(speechText: string): string {
  return `Pronuncia exactamente este mensaje, sin agregar, repetir ni reformular nada: ${JSON.stringify(
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

export function explicitConfirmation(value: string): boolean | null {
  const normalized = normalizeConfirmation(value)
  const negative =
    /\b(no|incorrecto|incorrecta|corregir|correccion|cambiar|equivocado|equivocada)\b/.test(
      normalized,
    )
  const positive =
    /\b(si|correcto|correcta|confirmo|confirmar|de acuerdo|esta bien|es correcto|es correcta)\b/.test(
      normalized,
    )

  if (positive === negative) return null
  return positive
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

export function shouldApplyFlowResponse(
  state: BusinessState,
  response: FlowResult,
  startingRequirementId: string,
  stateChanged: boolean,
): boolean {
  if (!stateChanged) return true
  if (state.result) {
    if (flowTransitionKey(state.result) === flowTransitionKey(response)) return false
    if (state.result.requirement_id !== response.requirement_id) return false
    return flowStage(response) > flowStage(state.result)
  }
  if (state.analysis) {
    return state.analysis.requirement_id === startingRequirementId
  }
  return true
}

export function analysisToolOutput(response: TurnAnalysis): Record<string, unknown> {
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
    terminal: record.next_action === "COMPLETE",
  }
}
