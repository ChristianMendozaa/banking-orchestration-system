export const APP_SURFACES = ["kiosk", "staff"] as const

export type AppSurface = (typeof APP_SURFACES)[number]

const PAGE_PREFIXES: Record<AppSurface, readonly string[]> = {
  kiosk: ["/kiosco"],
  staff: ["/login", "/ejecutivo", "/gerencial"],
}

const API_PREFIXES: Record<AppSurface, readonly string[]> = {
  kiosk: ["/api/v1/kiosk", "/api/v1/system/public-config"],
  staff: [
    "/api/v1/auth",
    "/api/v1/executive",
    "/api/v1/tickets",
    "/api/v1/management",
    "/api/v1/system/public-config",
  ],
}

export function parseAppSurface(value: string | undefined): AppSurface | null {
  return APP_SURFACES.find((surface) => surface === value) ?? null
}

export function appSurfaceHome(surface: AppSurface): string {
  return surface === "kiosk" ? "/kiosco" : "/login"
}

function matchesPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}

export function isPagePathAllowed(surface: AppSurface, pathname: string): boolean {
  return PAGE_PREFIXES[surface].some((prefix) => matchesPrefix(pathname, prefix))
}

export function isBackendPathAllowed(surface: AppSurface, pathname: string): boolean {
  return API_PREFIXES[surface].some((prefix) => matchesPrefix(pathname, prefix))
}
