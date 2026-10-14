// @module-tag functional
// @module-tag regression
// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { TicketDetail } from "../lib/types"

const request = vi.fn()

vi.mock("../components/providers/auth-provider", () => ({
  useAuth: () => ({ request }),
}))

import { IdentifierReveal } from "../components/executive/identifier-reveal"

function ticket(status: TicketDetail["status"], revealAvailable = true): TicketDetail {
  return {
    id: "ticket-1",
    status,
    identity: {
      status: "IDENTIFICADO",
      masked_identifier: "****5666",
      reveal_available: revealAvailable,
    },
  } as TicketDetail
}

afterEach(() => {
  cleanup()
  request.mockReset()
})

describe("IdentifierReveal", () => {
  it("does not offer the reveal before attention starts", () => {
    // The backend answers 409 outside active attention; the button used to be offered anyway
    // and the executive only found out by pressing it.
    render(<IdentifierReveal ticket={ticket("PENDIENTE")} onError={vi.fn()} onRevealed={vi.fn()} />)

    expect(screen.queryByRole("button")).toBeNull()
    expect(screen.getByText("Inicia la atención para revelar el CI completo.")).toBeTruthy()
    expect(screen.getByText("****5666")).toBeTruthy()
  })

  it("reveals during active attention and hides the value once attention ends", async () => {
    request.mockResolvedValue({ identifier: "6735666" })
    const onRevealed = vi.fn().mockResolvedValue(undefined)
    const view = render(
      <IdentifierReveal ticket={ticket("EN_ATENCION")} onError={vi.fn()} onRevealed={onRevealed} />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Revelar por 30 s" }))

    await waitFor(() => expect(screen.getByText("6735666")).toBeTruthy())
    expect(request).toHaveBeenCalledWith("/tickets/ticket-1/identifier/reveal", { method: "POST" })
    expect(onRevealed).toHaveBeenCalledTimes(1)

    view.rerender(
      <IdentifierReveal ticket={ticket("CERRADO", false)} onError={vi.fn()} onRevealed={onRevealed} />,
    )
    expect(screen.queryByText("6735666")).toBeNull()
    expect(screen.queryByRole("button")).toBeNull()
    expect(screen.getByText("CI completo no disponible para este caso histórico.")).toBeTruthy()
  })

  it("reports a rejected reveal to the page instead of showing a value", async () => {
    request.mockRejectedValue(new Error("El CI completo no esta disponible"))
    const onError = vi.fn()
    render(<IdentifierReveal ticket={ticket("EN_ATENCION")} onError={onError} onRevealed={vi.fn()} />)

    fireEvent.click(screen.getByRole("button", { name: "Revelar por 30 s" }))

    await waitFor(() => expect(onError).toHaveBeenLastCalledWith("El CI completo no esta disponible"))
    expect(screen.getByText("****5666")).toBeTruthy()
  })
})
