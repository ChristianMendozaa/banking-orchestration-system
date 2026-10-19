// @module-tag functional
// @module-tag usability
// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const context = vi.hoisted(() => ({
  listeningControlAvailable: true,
  listeningPaused: false,
  setListeningPaused: vi.fn(),
}))

vi.mock("../components/providers/kiosk-provider", () => ({
  useKiosk: () => context,
}))

import { ListeningToggle } from "../components/kiosk/listening-toggle"

describe("ListeningToggle", () => {
  beforeEach(() => {
    context.listeningControlAvailable = true
    context.listeningPaused = false
    context.setListeningPaused.mockReset()
  })

  afterEach(cleanup)

  it("is not offered while the kiosk keeps the microphone closed", () => {
    context.listeningControlAvailable = false
    const { container } = render(<ListeningToggle />)
    expect(container.innerHTML).toBe("")
  })

  it("pauses listening", () => {
    render(<ListeningToggle />)

    const button = screen.getByRole("button", { name: "Pausar escucha" })
    expect(button.getAttribute("aria-pressed")).toBe("false")
    fireEvent.click(button)

    expect(context.setListeningPaused).toHaveBeenCalledWith(true)
  })

  it("resumes listening once paused", () => {
    context.listeningPaused = true
    render(<ListeningToggle />)

    const button = screen.getByRole("button", { name: "Reanudar escucha" })
    expect(button.getAttribute("aria-pressed")).toBe("true")
    fireEvent.click(button)

    expect(context.setListeningPaused).toHaveBeenCalledWith(false)
  })
})
