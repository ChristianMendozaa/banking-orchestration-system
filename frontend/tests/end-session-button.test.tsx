// @module-tag functional
// @module-tag usability
// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const context = vi.hoisted(() => ({
  session: null as null | { session_id: string },
  hydrated: true,
  reset: vi.fn(),
}))

vi.mock("../components/providers/kiosk-provider", () => ({
  useKiosk: () => context,
}))

import { EndSessionButton } from "../components/kiosk/end-session-button"

describe("EndSessionButton", () => {
  beforeEach(() => {
    context.session = { session_id: "session-1" }
    context.hydrated = true
    context.reset.mockReset()
  })

  afterEach(cleanup)

  it("stays hidden without an active session", () => {
    context.session = null
    const { container } = render(<EndSessionButton />)
    expect(container.innerHTML).toBe("")
  })

  it("stays hidden until the kiosk state is hydrated", () => {
    context.hydrated = false
    const { container } = render(<EndSessionButton />)
    expect(container.innerHTML).toBe("")
  })

  it("asks for confirmation before ending the session", () => {
    render(<EndSessionButton />)

    fireEvent.click(screen.getByRole("button", { name: "Finalizar atención" }))

    expect(screen.getByRole("alertdialog")).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Continuar" }))
    expect(context.reset).not.toHaveBeenCalled()
  })

  it("keeps the session when the customer chooses to continue", () => {
    render(<EndSessionButton />)

    fireEvent.click(screen.getByRole("button", { name: "Finalizar atención" }))
    fireEvent.click(screen.getByRole("button", { name: "Continuar" }))
    expect(screen.queryByRole("alertdialog")).toBeNull()

    fireEvent.click(screen.getByRole("button", { name: "Finalizar atención" }))
    fireEvent.keyDown(window, { key: "Escape" })
    expect(screen.queryByRole("alertdialog")).toBeNull()

    expect(context.reset).not.toHaveBeenCalled()
  })

  it("ends the session once confirmed", () => {
    render(<EndSessionButton />)

    fireEvent.click(screen.getByRole("button", { name: "Finalizar atención" }))
    fireEvent.click(screen.getByRole("button", { name: "Sí, finalizar" }))

    expect(context.reset).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole("alertdialog")).toBeNull()
  })
})
