// @vitest-environment jsdom

import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useTicketDetail } from "../lib/use-ticket-detail"

const request = vi.fn()

// The hook's only dependency is the authenticated `request` the auth provider hands out.
// Mocking that instead of mounting AuthProvider keeps this about the hook: what it fetches,
// and what it does when the fetch fails.
vi.mock("../components/providers/auth-provider", () => ({
  useAuth: () => ({ request }),
}))

afterEach(() => {
  request.mockReset()
  vi.unstubAllGlobals()
})

describe("useTicketDetail", () => {
  it("loads the ticket on mount and escapes the id into the path", async () => {
    const ticket = { id: "a/b", status: "PENDIENTE" }
    request.mockResolvedValue(ticket)

    const { result } = renderHook(() => useTicketDetail("a/b"))

    await waitFor(() => expect(result.current.ticket).toEqual(ticket))
    expect(request).toHaveBeenCalledWith("/tickets/a%2Fb")
    expect(result.current.error).toBeNull()
  })

  it("surfaces a failure as a message instead of leaving the page blank", async () => {
    request.mockRejectedValue(new Error("El ticket ya no está disponible"))

    const { result } = renderHook(() => useTicketDetail("ticket-1"))

    await waitFor(() =>
      expect(result.current.error).toBe("El ticket ya no está disponible"),
    )
    expect(result.current.ticket).toBeNull()
  })

  it("clears a previous error once a reload succeeds", async () => {
    // An executive who loses connectivity mid-shift and then recovers must not be left
    // staring at a stale error banner over freshly loaded data.
    request.mockRejectedValueOnce(new Error("Sin conexión"))
    const { result } = renderHook(() => useTicketDetail("ticket-1"))
    await waitFor(() => expect(result.current.error).toBe("Sin conexión"))

    const ticket = { id: "ticket-1", status: "CERRADO" }
    request.mockResolvedValueOnce(ticket)
    await result.current.reload()

    await waitFor(() => {
      expect(result.current.ticket).toEqual(ticket)
      expect(result.current.error).toBeNull()
    })
  })
})
