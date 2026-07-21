import { appSurfaceHome, parseAppSurface } from "@/lib/app-surface"
import { redirect } from "next/navigation"
import { connection } from "next/server"

export default async function HomePage() {
  await connection()
  const surface = parseAppSurface(process.env.APP_SURFACE)
  if (!surface) throw new Error("APP_SURFACE debe ser 'kiosk' o 'staff'")
  redirect(appSurfaceHome(surface))
}
