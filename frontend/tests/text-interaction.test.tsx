// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const context = vi.hoisted(() => ({
  analysis: null as null | {
    next_action: string
    speech_text: string
    customer_summary: string
  },
  result: null,
  submitTextTurn: vi.fn(),
  confirmText: vi.fn(),
  selectInteractionMode: vi.fn(),
}))

vi.mock("../components/providers/kiosk-provider", () => ({
  useKiosk: () => context,
}))

import { TextInteraction } from "../components/kiosk/text-interaction"

describe("TextInteraction", () => {
  beforeEach(() => {
    context.analysis = null
    context.submitTextTurn.mockReset()
    context.confirmText.mockReset()
    context.selectInteractionMode.mockReset()
  })

  it("permite enviar una solicitud escrita y volver a voz", async () => {
    context.submitTextTurn.mockResolvedValue({})
    render(<TextInteraction />)

    fireEvent.change(screen.getByLabelText("Tu mensaje"), {
      target: { value: "Necesito bloquear mi tarjeta" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }))

    await waitFor(() =>
      expect(context.submitTextTurn).toHaveBeenCalledWith(
        "Necesito bloquear mi tarjeta",
      ),
    )
    fireEvent.click(screen.getByRole("button", { name: "Prefiero hablar" }))
    expect(context.selectInteractionMode).toHaveBeenCalledWith("voice")
  })

  it("presenta decisiones explícitas cuando el resumen requiere confirmación", async () => {
    context.analysis = {
      next_action: "CONFIRM",
      speech_text: "Confirma si entendí correctamente.",
      customer_summary: "Necesitas bloquear tu tarjeta.",
    }
    context.confirmText.mockResolvedValue({})
    render(<TextInteraction />)

    fireEvent.click(screen.getByRole("button", { name: "Sí, es correcto" }))
    await waitFor(() => expect(context.confirmText).toHaveBeenCalledWith(true))
  })
})
