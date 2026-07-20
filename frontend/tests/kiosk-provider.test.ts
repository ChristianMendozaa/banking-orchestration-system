import { describe, expect, it } from "vitest"

import { kioskRouteForState } from "../lib/kiosk-realtime"
import type { FlowResult, KioskSession } from "../lib/types"

const session: KioskSession = {
  session_id: "session-1",
  session_token: "secret",
  status: "CREATED",
  expires_at: "2099-01-01T00:00:00Z",
}

function result(
  nextAction: FlowResult["next_action"],
  resolutionType: FlowResult["resolution_type"] = null,
): FlowResult {
  return {
    session_id: session.session_id,
    requirement_id: "requirement-1",
    status:
      nextAction === "COMPLETE"
        ? "ASSIGNED"
        : nextAction === "IDENTIFY"
          ? "AWAITING_IDENTIFICATION"
          : "LISTENING",
    next_action: nextAction,
    customer_summary: "Necesitas reportar un posible fraude.",
    priority: "CRITICO",
    identification_status: null,
    resolution_type: resolutionType,
    ticket: null,
    executive: null,
    response: null,
    speech_text: "Mensaje",
    tracking_information: null,
    grounding_status: "NOT_APPLICABLE",
    citations: [],
  }
}

describe("kioskRouteForState", () => {
  it("deriva una sola ruta de la instantánea de negocio", () => {
    expect(kioskRouteForState({ session: null, result: null })).toBe("/kiosco")
    expect(kioskRouteForState({ session, result: null })).toBe("/kiosco/voz")
    expect(kioskRouteForState({ session, result: result("IDENTIFY") })).toBe(
      "/kiosco/identificacion",
    )
    expect(
      kioskRouteForState({ session, result: result("COMPLETE", "HUMAN") }),
    ).toBe("/kiosco/ticket")
    expect(
      kioskRouteForState({ session, result: result("COMPLETE", "AUTOMATIC") }),
    ).toBe("/kiosco/respuesta")
  })
})
