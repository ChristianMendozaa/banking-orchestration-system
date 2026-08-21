import type { FlowResult, KioskSession, TurnAnalysis } from "@/lib/types"

export function kioskRouteForState(state: {
  session: KioskSession | null
  result: FlowResult | null
  analysis?: TurnAnalysis | null
}): string {
  if (!state.session) return "/kiosco"
  if (state.result?.next_action === "IDENTIFY") return "/kiosco/identificacion"
  // A human handoff is the end of the kiosk's part: an executive owns the case from here.
  // An answer the kiosk found by itself is not the end of anything -- the person is still
  // standing there and may well have a second question -- so it stays inside the
  // conversation instead of taking over the screen, and the microphone stays where it was.
  if (
    state.result?.next_action === "COMPLETE" &&
    state.result.resolution_type !== "AUTOMATIC"
  ) {
    return "/kiosco/ticket"
  }
  if (state.analysis?.next_action === "DECLINE") return "/kiosco/respuesta"
  return "/kiosco/voz"
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
