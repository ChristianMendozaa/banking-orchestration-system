import { describe, expect, it } from "vitest"

import {
  analysisTransitionKey,
  businessTransitionKey,
  flowTransitionKey,
  isTerminalFlowResult,
  shouldApplyAnalysisResponse,
  shouldApplyFlowResponse,
} from "../lib/kiosk-flow"
import type { FlowResult, TurnAnalysis } from "../lib/types"

const analysis: TurnAnalysis = {
  requirement_id: "requirement-1",
  status: "AWAITING_CONFIRMATION",
  summary: "Reporte de fraude en tarjeta.",
  customer_summary: "Necesitas reportar un fraude en tu tarjeta.",
  category: "REPORTE_FRAUDE",
  priority: "CRITICO",
  consultation_level: "SENSIBLE",
  confidence: 0.99,
  clarification_question: null,
  pii_types: [],
  next_action: "CONFIRM",
  speech_text: "Me confirmas si necesitas reportar un fraude en tu tarjeta.",
}

const completed: FlowResult = {
  session_id: "session-1",
  requirement_id: "requirement-1",
  status: "ASSIGNED",
  next_action: "COMPLETE",
  customer_summary: analysis.customer_summary,
  priority: analysis.priority,
  identification_status: "IDENTIFICADO",
  resolution_type: "HUMAN",
  ticket: {
    id: "ticket-1",
    number: 4,
    status: "PENDIENTE",
    estimated_wait_minutes: 3,
  },
  executive: null,
  response: null,
  speech_text: "Tu ticket es el número 4.",
  tracking_information: null,
  grounding_status: "NOT_APPLICABLE",
  citations: [],
}

describe("transition keys", () => {
  it("correlates analysis and tickets with stable keys", () => {
    expect(analysisTransitionKey(analysis)).toBe("requirement-1:CONFIRM")
    expect(flowTransitionKey(completed)).toBe("ticket:ticket-1")
  })

  it("does not treat an automatic answer as the end of the session", () => {
    // An answer the kiosk produced by itself leaves the customer standing there, and the
    // backend opens a second case for a follow-up question, so closing the session on
    // COMPLETE would hang up on someone mid-conversation.
    expect(isTerminalFlowResult({ ...completed, resolution_type: "AUTOMATIC" })).toBe(
      false,
    )
  })

  it("still closes the session on a human handoff", () => {
    expect(isTerminalFlowResult(completed)).toBe(true)
    expect(isTerminalFlowResult({ ...completed, resolution_type: "AUTOMATIC" })).toBe(
      false,
    )
  })
})

describe("business response ordering", () => {
  it("does not let a delayed analysis erase identification or closure", () => {
    const identify = {
      ...completed,
      next_action: "IDENTIFY" as const,
      status: "AWAITING_IDENTIFICATION" as const,
      ticket: null,
    }

    expect(
      shouldApplyAnalysisResponse(
        { analysis, result: identify },
        analysis,
        null,
        true,
      ),
    ).toBe(false)
    expect(
      shouldApplyAnalysisResponse(
        { analysis, result: completed },
        analysis,
        null,
        true,
      ),
    ).toBe(false)
  })

  it("accepts a clarification's advance if only its initial phase was reconciled", () => {
    const clarified = { ...analysis, requirement_id: "requirement-2" }
    expect(
      shouldApplyAnalysisResponse(
        { analysis, result: null },
        clarified,
        analysis.requirement_id,
        true,
      ),
    ).toBe(true)
  })

  it("does not revive a request that was already rejected", () => {
    const capture = {
      ...completed,
      next_action: "CAPTURE" as const,
      status: "LISTENING" as const,
      ticket: null,
    }
    expect(
      shouldApplyAnalysisResponse(
        { analysis: null, result: capture },
        analysis,
        analysis.requirement_id,
        true,
      ),
    ).toBe(false)
    expect(
      shouldApplyAnalysisResponse(
        { analysis: null, result: capture },
        { ...analysis, requirement_id: "requirement-2" },
        null,
        true,
      ),
    ).toBe(true)
  })

  it("lets a follow-up question replace an automatic answer", () => {
    // A different requirement_id normally means a stale response arriving late. After an
    // automatic answer it means the opposite: the customer asked something else, and that
    // second requirement is the current one.
    const answered = { ...completed, resolution_type: "AUTOMATIC" as const }
    const followUp = {
      ...answered,
      requirement_id: "requirement-2",
      ticket: { ...completed.ticket!, id: "ticket-2", number: 5 },
    }
    expect(
      shouldApplyFlowResponse(
        { analysis: null, result: answered },
        followUp,
        followUp.requirement_id,
        true,
      ),
    ).toBe(true)
    // ...but a stale one after a human handoff is still discarded.
    expect(
      shouldApplyFlowResponse(
        { analysis: null, result: completed },
        {
          ...completed,
          requirement_id: "requirement-2",
          ticket: { ...completed.ticket!, id: "ticket-2", number: 5 },
        },
        "requirement-2",
        true,
      ),
    ).toBe(false)
  })

  it("does not let a delayed IDENTIFY replace a COMPLETE ticket", () => {
    const identify = {
      ...completed,
      next_action: "IDENTIFY" as const,
      status: "AWAITING_IDENTIFICATION" as const,
      ticket: null,
    }
    expect(
      shouldApplyFlowResponse(
        { analysis, result: completed },
        identify,
        analysis.requirement_id,
        true,
      ),
    ).toBe(false)
    expect(businessTransitionKey({ analysis, result: completed })).toBe(
      "ticket:ticket-1",
    )
  })

})
