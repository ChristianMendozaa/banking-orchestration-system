import type { NextRequest } from "next/server"
import { isBackendPathAllowed, parseAppSurface } from "@/lib/app-surface"

export const dynamic = "force-dynamic"

type RouteContext = { params: Promise<{ path: string[] }> }

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params
  const surface = parseAppSurface(process.env.APP_SURFACE)
  if (!surface) {
    return Response.json(
      { code: "FRONTEND_CONFIG_ERROR", message: "APP_SURFACE no está configurada" },
      { status: 503 },
    )
  }

  const apiPath = `/${path.join("/")}`
  if (!isBackendPathAllowed(surface, apiPath)) {
    return Response.json(
      { code: "FRONTEND_ROUTE_NOT_AVAILABLE", message: "Recurso no disponible" },
      { status: 404 },
    )
  }

  const backend = process.env.BACKEND_INTERNAL_URL
  if (!backend) {
    return Response.json(
      { code: "FRONTEND_CONFIG_ERROR", message: "BACKEND_INTERNAL_URL no está configurada" },
      { status: 503 },
    )
  }

  const url = new URL(path.map(encodeURIComponent).join("/"), `${backend.replace(/\/$/, "")}/`)
  url.search = request.nextUrl.search
  const headers = new Headers(request.headers)
  headers.delete("host")
  headers.delete("content-length")
  headers.delete("connection")

  try {
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : await request.arrayBuffer(),
      redirect: "manual",
      cache: "no-store",
    })
    const responseHeaders = new Headers(upstream.headers)
    responseHeaders.delete("content-encoding")
    responseHeaders.delete("content-length")
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    })
  } catch {
    return Response.json(
      { code: "BACKEND_UNAVAILABLE", message: "El backend no está disponible" },
      { status: 503 },
    )
  }
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
export const OPTIONS = proxy
