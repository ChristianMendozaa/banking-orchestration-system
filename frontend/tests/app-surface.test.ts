import { NextRequest } from "next/server"
import { afterEach, describe, expect, it } from "vitest"

import {
  appSurfaceHome,
  isBackendPathAllowed,
  isPagePathAllowed,
  parseAppSurface,
} from "../lib/app-surface"
import { proxy } from "../proxy"

const originalSurface = process.env.APP_SURFACE

afterEach(() => {
  if (originalSurface === undefined) delete process.env.APP_SURFACE
  else process.env.APP_SURFACE = originalSurface
})

describe("app surface", () => {
  it("validates the mode and defines an exclusive entry", () => {
    expect(parseAppSurface("kiosk")).toBe("kiosk")
    expect(parseAppSurface("staff")).toBe("staff")
    expect(parseAppSurface("otro")).toBeNull()
    expect(appSurfaceHome("kiosk")).toBe("/kiosco")
    expect(appSurfaceHome("staff")).toBe("/login")
  })

  it("separates kiosk and staff pages", () => {
    expect(isPagePathAllowed("kiosk", "/kiosco/voz")).toBe(true)
    expect(isPagePathAllowed("kiosk", "/login")).toBe(false)
    expect(isPagePathAllowed("staff", "/ejecutivo/caso/123")).toBe(true)
    expect(isPagePathAllowed("staff", "/gerencial/conocimiento")).toBe(true)
    expect(isPagePathAllowed("staff", "/kiosco")).toBe(false)
  })

  it("separates API families without accepting partial prefixes", () => {
    expect(isBackendPathAllowed("kiosk", "/api/v1/kiosk/sessions")).toBe(true)
    expect(isBackendPathAllowed("kiosk", "/api/v1/auth/login")).toBe(false)
    expect(isBackendPathAllowed("staff", "/api/v1/management/metrics")).toBe(true)
    expect(isBackendPathAllowed("staff", "/api/v1/tickets/123")).toBe(true)
    expect(isBackendPathAllowed("staff", "/api/v1/kiosk/sessions")).toBe(false)
    expect(isBackendPathAllowed("staff", "/api/v1/authentication")).toBe(false)
  })
})

describe("surface proxy", () => {
  it("redirects the root of each instance", () => {
    process.env.APP_SURFACE = "kiosk"
    const kiosk = proxy(new NextRequest("http://localhost:3000/"))
    expect(kiosk.status).toBe(307)
    expect(kiosk.headers.get("location")).toBe("http://localhost:3000/kiosco")
    expect(kiosk.headers.get("content-security-policy")).toContain("'strict-dynamic'")
    expect(kiosk.headers.get("content-security-policy")).not.toContain(
      "upgrade-insecure-requests",
    )

    process.env.APP_SURFACE = "staff"
    const staff = proxy(new NextRequest("http://localhost:3001/"))
    expect(staff.status).toBe(307)
    expect(staff.headers.get("location")).toBe("http://localhost:3001/login")
  })

  it("hides foreign routes and fails closed without configuration", () => {
    process.env.APP_SURFACE = "kiosk"
    expect(proxy(new NextRequest("http://localhost:3000/login")).status).toBe(404)

    process.env.APP_SURFACE = "staff"
    expect(proxy(new NextRequest("http://localhost:3001/kiosco")).status).toBe(404)

    delete process.env.APP_SURFACE
    expect(proxy(new NextRequest("http://localhost:3000/")).status).toBe(503)
  })
})
