import { appSurfaceHome, isPagePathAllowed, parseAppSurface } from "./lib/app-surface"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

function contentSecurityPolicy(nonce: string): string {
  const development = process.env.NODE_ENV === "development"
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self' https://api.openai.com wss://api.openai.com",
    "media-src 'self' blob:",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ")
}

function secured(response: NextResponse, policy: string): NextResponse {
  response.headers.set("Content-Security-Policy", policy)
  return response
}

export function proxy(request: NextRequest): NextResponse {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64")
  const policy = contentSecurityPolicy(nonce)
  const surface = parseAppSurface(process.env.APP_SURFACE)
  if (!surface) {
    return secured(new NextResponse("Frontend no configurado", { status: 503 }), policy)
  }

  if (request.nextUrl.pathname === "/") {
    return secured(
      NextResponse.redirect(new URL(appSurfaceHome(surface), request.url)),
      policy,
    )
  }

  if (!isPagePathAllowed(surface, request.nextUrl.pathname)) {
    return secured(new NextResponse("Not Found", { status: 404 }), policy)
  }

  const requestHeaders = new Headers(request.headers)
  requestHeaders.set("x-nonce", nonce)
  requestHeaders.set("Content-Security-Policy", policy)
  return secured(NextResponse.next({ request: { headers: requestHeaders } }), policy)
}

export const config = {
  matcher: [
    "/",
    "/kiosco/:path*",
    "/login/:path*",
    "/ejecutivo/:path*",
    "/gerencial/:path*",
  ],
}
