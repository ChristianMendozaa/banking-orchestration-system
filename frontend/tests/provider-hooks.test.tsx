// @vitest-environment jsdom

import { act, render, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  AuthProvider,
  useAuth,
} from "../components/providers/auth-provider"
import type { TokenResponse } from "../lib/types"
import { useIntervalRefresh } from "../lib/use-interval-refresh"

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("provider helpers", () => {
  it("mantiene un solo temporizador y lo limpia al desmontar", () => {
    vi.useFakeTimers()
    const callback = vi.fn()
    const { unmount } = renderHook(() => useIntervalRefresh(callback, 1_000))

    act(() => vi.advanceTimersByTime(2_500))
    expect(callback).toHaveBeenCalledTimes(2)
    unmount()
    act(() => vi.advanceTimersByTime(2_000))
    expect(callback).toHaveBeenCalledTimes(2)
  })

  it("comparte una sola rotación de refresh entre errores 401 concurrentes", async () => {
    const session = (accessToken: string): TokenResponse => ({
      access_token: accessToken,
      token_type: "bearer",
      expires_in: 1_800,
      user: {
        id: "user-1",
        email: "gerencia@example.test",
        role: "MANAGER",
        executive_id: null,
      },
    })
    let refreshCalls = 0
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1
        return Response.json(session(refreshCalls === 1 ? "initial" : "rotated"))
      }
      const authorization = new Headers(init?.headers).get("authorization")
      if (authorization === "Bearer initial") {
        return Response.json({ code: "INVALID_TOKEN" }, { status: 401 })
      }
      return Response.json({ ok: true })
    })
    vi.stubGlobal("fetch", fetchMock)

    let context: ReturnType<typeof useAuth> | null = null
    function Probe() {
      context = useAuth()
      return null
    }
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await waitFor(() => expect(context?.loading).toBe(false))

    await act(async () => {
      await Promise.all([
        context!.request<{ ok: boolean }>("/management/metrics"),
        context!.request<{ ok: boolean }>("/management/cases"),
      ])
    })

    expect(refreshCalls).toBe(2)
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/auth/refresh")),
    ).toHaveLength(2)
  })
})
