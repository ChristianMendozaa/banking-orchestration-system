// @module-tag functional
// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { TicketDetail } from "../lib/types"

const request = vi.fn()

vi.mock("../components/providers/auth-provider", () => ({
  useAuth: () => ({ request }),
}))

import { StatusSelector } from "../components/executive/status-selector"

const NOTE = "El cliente necesita revisar un crédito"
const candidates = {
  items: [
    {
      id: "exec-2",
      name: "Patricia Quispe",
      title: "Banca Digital",
      window_number: "Ventanilla 5",
      status: "OCUPADO",
      active_load: 2,
    },
  ],
}

function ticket(status: TicketDetail["status"]): TicketDetail {
  return { id: "ticket-1", status, version: 4, resolution_outcome: null } as TicketDetail
}

async function openForm() {
  fireEvent.click(screen.getByRole("button", { name: "Derivar a otro ejecutivo" }))
  await waitFor(() => expect(screen.getByRole("option", { name: /Patricia Quispe/ })).toBeTruthy())
}

afterEach(() => {
  cleanup()
  request.mockReset()
})

describe("case derivation", () => {
  it("replaces the derived closing label with a real handoff", async () => {
    request.mockResolvedValueOnce(candidates)
    render(<StatusSelector ticket={ticket("EN_ATENCION")} onUpdated={vi.fn()} onDerived={vi.fn()} />)

    const outcomes = Array.from(
      (screen.getByLabelText("Resultado de la atención") as HTMLSelectElement).options,
    ).map((option) => option.value)
    expect(outcomes).not.toContain("DERIVADO")
    expect(outcomes).toContain("RESUELTO")

    await openForm()
    expect(request).toHaveBeenCalledWith("/tickets/ticket-1/derivation/candidates")
    // A colleague who is mid-attention is still a destination: the case waits in their queue.
    expect(screen.getByRole("option", { name: /Patricia Quispe/ }).textContent).toContain(
      "En atención · 2 en cola",
    )
  })

  it("lets the routing engine choose when no colleague is picked", async () => {
    const derivation = { id: "ticket-1", number: "12", executive_name: "Carlos Mamani" }
    request.mockResolvedValueOnce(candidates).mockResolvedValueOnce(derivation)
    const onDerived = vi.fn()
    render(<StatusSelector ticket={ticket("PENDIENTE")} onUpdated={vi.fn()} onDerived={onDerived} />)
    await openForm()

    const submit = screen.getByRole("button", { name: "Derivar caso" }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText("Motivo de la derivación"), { target: { value: NOTE } })
    fireEvent.click(submit)

    await waitFor(() => expect(onDerived).toHaveBeenCalledWith(derivation))
    expect(request).toHaveBeenLastCalledWith("/tickets/ticket-1/derivation", {
      method: "POST",
      body: JSON.stringify({ expected_version: 4, note: NOTE, executive_id: null }),
    })
  })

  it("sends the chosen colleague and keeps the form open when the backend refuses", async () => {
    request
      .mockResolvedValueOnce(candidates)
      .mockRejectedValueOnce(new Error("El ticket fue actualizado por otro proceso"))
    const onDerived = vi.fn()
    render(<StatusSelector ticket={ticket("EN_ATENCION")} onUpdated={vi.fn()} onDerived={onDerived} />)
    await openForm()

    fireEvent.change(screen.getByLabelText("Derivar a"), { target: { value: "exec-2" } })
    fireEvent.change(screen.getByLabelText("Motivo de la derivación"), { target: { value: NOTE } })
    fireEvent.click(screen.getByRole("button", { name: "Derivar caso" }))

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("El ticket fue actualizado por otro proceso"),
    )
    expect(JSON.parse(request.mock.calls[1][1].body).executive_id).toBe("exec-2")
    expect(onDerived).not.toHaveBeenCalled()
    expect(screen.getByLabelText("Motivo de la derivación")).toBeTruthy()
  })
})
