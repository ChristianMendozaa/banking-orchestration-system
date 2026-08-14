// @vitest-environment jsdom

import { act, render, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  createSession: vi.fn(),
  sessionRequest: vi.fn(),
  replace: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  usePathname: () => "/kiosco",
  useRouter: () => ({ replace: mocks.replace }),
}))

vi.mock("../lib/kiosk-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/kiosk-api")>()
  return {
    ...original,
    createKioskSession: mocks.createSession,
    kioskSessionRequest: mocks.sessionRequest,
  }
})

import {
  KioskProvider,
  useKiosk,
} from "../components/providers/kiosk-provider"

describe("KioskProvider text flow", () => {
  beforeEach(() => {
    sessionStorage.clear()
    mocks.createSession.mockReset()
    mocks.sessionRequest.mockReset()
    mocks.replace.mockReset()
  })

  it("creates, retains, and processes a session without opening the voice transport", async () => {
    const session = {
      session_id: "session-text",
      session_token: "token",
      status: "CREATED",
      expires_at: "2099-01-01T00:00:00Z",
    }
    const analysis = {
      requirement_id: "requirement-text",
      status: "AWAITING_CONFIRMATION",
      summary: "Bloqueo de tarjeta.",
      customer_summary: "Necesitas bloquear tu tarjeta.",
      category: "BLOQUEO_TARJETA",
      priority: "ALTO",
      consultation_level: "SENSIBLE",
      confidence: 0.99,
      clarification_question: null,
      pii_types: [],
      next_action: "CONFIRM",
      speech_text: "Confirma si necesitas bloquear tu tarjeta.",
    }
    mocks.createSession.mockResolvedValue(session)
    mocks.sessionRequest.mockImplementation(
      async (_session: unknown, suffix: string) =>
        suffix === "/turns" ? analysis : { accepted: 2 },
    )

    let kiosk: ReturnType<typeof useKiosk> | null = null
    function Probe() {
      kiosk = useKiosk()
      return null
    }
    render(
      <KioskProvider>
        <Probe />
      </KioskProvider>,
    )
    await waitFor(() => expect(kiosk?.hydrated).toBe(true))

    await act(async () => kiosk!.beginSession(true))
    act(() => kiosk!.selectInteractionMode("text"))
    await act(async () => kiosk!.submitTextTurn("Necesito bloquear mi tarjeta"))

    const current = kiosk as unknown as ReturnType<typeof useKiosk>
    expect(mocks.createSession).toHaveBeenCalledWith(true)
    expect(current.interactionMode).toBe("text")
    expect(current.analysis?.requirement_id).toBe("requirement-text")
    await waitFor(() =>
      expect(mocks.sessionRequest).toHaveBeenCalledWith(
        session,
        "/conversation/messages",
        expect.objectContaining({ method: "POST" }),
      ),
    )
  })
})
