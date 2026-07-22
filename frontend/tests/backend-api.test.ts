import { NextRequest } from "next/server"
import { afterEach, describe, expect, it, vi } from "vitest"

import { proxyBackendRequest } from "../app/backend-api/[...path]/route"

const originalSurface = process.env.APP_SURFACE
const originalBackend = process.env.BACKEND_INTERNAL_URL

afterEach(() => {
  vi.unstubAllGlobals()
  if (originalSurface === undefined) delete process.env.APP_SURFACE
  else process.env.APP_SURFACE = originalSurface
  if (originalBackend === undefined) delete process.env.BACKEND_INTERNAL_URL
  else process.env.BACKEND_INTERNAL_URL = originalBackend
})

describe("backend API proxy", () => {
  it("bloquea familias ajenas antes de contactar al backend", async () => {
    process.env.APP_SURFACE = "kiosk"
    process.env.BACKEND_INTERNAL_URL = "http://backend:8000"
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    const response = await proxyBackendRequest(
      new NextRequest("http://localhost/backend-api/api/v1/auth/me"),
      { params: Promise.resolve({ path: ["api", "v1", "auth", "me"] }) },
    )

    expect(response.status).toBe(404)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("conserva método, query y cabeceras de una solicitud permitida", async () => {
    process.env.APP_SURFACE = "kiosk"
    process.env.BACKEND_INTERNAL_URL = "http://backend:8000/"
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json", "Content-Encoding": "gzip" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const response = await proxyBackendRequest(
      new NextRequest(
        "http://localhost/backend-api/api/v1/kiosk/sessions?source=test",
        {
          method: "POST",
          headers: { "X-Session-Token": "session-secret" },
          body: JSON.stringify({ preferential_attention: true }),
        },
      ),
      { params: Promise.resolve({ path: ["api", "v1", "kiosk", "sessions"] }) },
    )

    expect(response.status).toBe(200)
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit]
    expect(url.toString()).toBe("http://backend:8000/api/v1/kiosk/sessions?source=test")
    expect(init.method).toBe("POST")
    expect(new Headers(init.headers).get("x-session-token")).toBe("session-secret")
    expect(response.headers.has("content-encoding")).toBe(false)
  })
})
