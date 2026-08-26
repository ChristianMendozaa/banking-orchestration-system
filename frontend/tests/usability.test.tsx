// @module-tag functional
// @module-tag usability
// @vitest-environment jsdom

import axe from "axe-core"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const context = vi.hoisted(() => ({
  analysis: null as null | {
    customer_summary: string
    next_action: string
    speech_text: string
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

describe("TextInteraction accessibility and clarity support", () => {
  beforeEach(() => {
    context.analysis = null
    context.submitTextTurn.mockReset()
    context.confirmText.mockReset()
    context.selectInteractionMode.mockReset()
  })

  it("exposes labelled controls, live updates, and no axe naming violations", async () => {
    const { container } = render(<TextInteraction />)

    expect(screen.getByLabelText("Tu mensaje").hasAttribute("required")).toBe(true)
    expect((screen.getByRole("button", { name: "Enviar" }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect(
      (screen.getByRole("button", { name: "Prefiero hablar" }) as HTMLButtonElement).disabled,
    ).toBe(false)
    expect(screen.getByText("Asistente").parentElement?.getAttribute("aria-live")).toBe("polite")

    const results = await axe.run(container, {
      runOnly: {
        type: "rule",
        values: [
          "aria-allowed-attr",
          "aria-valid-attr",
          "aria-valid-attr-value",
          "button-name",
          "label",
        ],
      },
    })
    expect(results.violations).toEqual([])
  })

  it("offers explicit and understandable choices when confirmation is required", () => {
    context.analysis = {
      customer_summary: "Necesitas bloquear tu tarjeta.",
      next_action: "CONFIRM",
      speech_text: "Confirma si entendí correctamente.",
    }
    render(<TextInteraction />)

    expect(
      (screen.getByRole("button", { name: "Sí, es correcto" }) as HTMLButtonElement).disabled,
    ).toBe(false)
    expect(
      (screen.getByRole("button", { name: "No, quiero corregir" }) as HTMLButtonElement).disabled,
    ).toBe(false)
    expect(screen.getByText("Necesitas bloquear tu tarjeta.").isConnected).toBe(true)
  })
})
