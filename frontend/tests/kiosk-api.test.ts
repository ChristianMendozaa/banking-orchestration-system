import { afterEach, describe, expect, it, vi } from "vitest"

import { createKioskSession, kioskSessionRequest } from "../lib/kiosk-api"
import type { KioskSession } from "../lib/types"

afterEach(() => vi.unstubAllGlobals())

describe("kiosk API client", () => {
  it("centraliza la creación y la autenticación de la sesión", async () => {
    const session: KioskSession = {
      session_id: "session-1",
      session_token: "secret",
      status: "CREATED",
      expires_at: "2099-01-01T00:00:00Z",
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(session, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ status: "CREATED" }))
    vi.stubGlobal("fetch", fetchMock)

    await expect(createKioskSession(true)).resolves.toEqual(session)
    await kioskSessionRequest(session, "")

    expect(fetchMock.mock.calls[0][0]).toBe("/backend-api/api/v1/kiosk/sessions")
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      preferential_attention: true,
    })
    const secondHeaders = new Headers(fetchMock.mock.calls[1][1].headers)
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/backend-api/api/v1/kiosk/sessions/session-1",
    )
    expect(secondHeaders.get("x-session-token")).toBe("secret")
  })
})
