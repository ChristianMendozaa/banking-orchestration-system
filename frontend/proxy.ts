import { appSurfaceHome, isPagePathAllowed, parseAppSurface } from "./lib/app-surface"
import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"

export function proxy(request: NextRequest): NextResponse {
  const surface = parseAppSurface(process.env.APP_SURFACE)
  if (!surface) {
    return new NextResponse("Frontend no configurado", { status: 503 })
  }

  if (request.nextUrl.pathname === "/") {
    return NextResponse.redirect(new URL(appSurfaceHome(surface), request.url))
  }

  if (!isPagePathAllowed(surface, request.nextUrl.pathname)) {
    return new NextResponse("Not Found", { status: 404 })
  }

  return NextResponse.next()
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
