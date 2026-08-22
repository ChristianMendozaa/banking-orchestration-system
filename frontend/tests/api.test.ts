import { afterEach, describe, expect, it, vi } from "vitest"

import { ApiError, apiDownload, errorMessage } from "../lib/api"

afterEach(() => vi.unstubAllGlobals())

describe("apiDownload", () => {
  // The staff dashboards name the file a manager ends up with on disk, and the name only
  // ever arrives inside a content-disposition header. Every branch below is a header a real
  // backend sends, and the fallback is what stops a download from being saved as
  // "undefined".
  it("prefers the RFC 5987 filename and decodes it", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("pdf-bytes", {
        headers: {
          "content-disposition":
            "attachment; filename=\"fallback.pdf\"; filename*=UTF-8''resoluci%C3%B3n.pdf",
        },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const { blob, fileName } = await apiDownload("/tickets/1/export", "token")

    expect(fileName).toBe("resolución.pdf")
    expect(await blob.text()).toBe("pdf-bytes")
    const headers = new Headers(fetchMock.mock.calls[0][1].headers)
    expect(headers.get("authorization")).toBe("Bearer token")
  })

  it("falls back to the plain filename, then to a default", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response("a", {
            headers: { "content-disposition": 'attachment; filename="reporte.pdf"' },
          }),
        )
        .mockResolvedValueOnce(new Response("b")),
    )

    await expect(apiDownload("/a", "t")).resolves.toMatchObject({ fileName: "reporte.pdf" })
    await expect(apiDownload("/b", "t")).resolves.toMatchObject({ fileName: "documento.pdf" })
  })

  it("raises the backend's error code rather than returning an empty file", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({ code: "FORBIDDEN", message: "Sin permisos" }, { status: 403 }),
      ),
    )

    await expect(apiDownload("/a", "t")).rejects.toMatchObject({
      code: "FORBIDDEN",
      status: 403,
      message: "Sin permisos",
    })
  })

  it("survives an error response that is not JSON at all", async () => {
    // A proxy or gateway failing in front of the backend returns HTML, not the error shape.
    // Parsing it must not throw over the top of the real failure.
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("<html>502</html>", { status: 502, statusText: "Bad Gateway" })),
    )

    const failure = await apiDownload("/a", "t").catch((reason: unknown) => reason)
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure).toMatchObject({ status: 502, code: "HTTP_ERROR", message: "Bad Gateway" })
  })
})

describe("errorMessage", () => {
  it("unwraps an Error and names anything else", () => {
    expect(errorMessage(new Error("se perdió la conexión"))).toBe("se perdió la conexión")
    expect(errorMessage(new ApiError(409, { message: "Estado inválido" }))).toBe(
      "Estado inválido",
    )
    // Callers pass whatever a `catch` gave them, which is not always an Error.
    expect(errorMessage("texto suelto")).toBe("Ocurrió un error inesperado")
    expect(errorMessage(undefined)).toBe("Ocurrió un error inesperado")
  })
})
