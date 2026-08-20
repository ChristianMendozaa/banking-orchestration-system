"use client"

import { SystemConfigProvider } from "@/components/providers/system-config-provider"
import { createContext, useContext, useMemo } from "react"

interface RuntimeConfig {
  /** Where a browser reaches the backend directly. Only the voice WebSocket needs it. */
  voiceBaseUrl: string
}

const RuntimeConfigContext = createContext<RuntimeConfig>({ voiceBaseUrl: "" })

/**
 * Server-provided values, read from the environment at request time.
 *
 * Deliberately not `NEXT_PUBLIC_*`: those are substituted into the client bundle when the
 * image is built, which would make the backend's address a property of the image rather
 * than of the deployment -- changing it would mean a rebuild, and a stale value would be
 * baked into every container running that image.
 */
export function useRuntimeConfig(): RuntimeConfig {
  return useContext(RuntimeConfigContext)
}

export function AppProviders({
  children,
  voiceBaseUrl,
}: {
  children: React.ReactNode
  voiceBaseUrl: string
}) {
  const runtime = useMemo(() => ({ voiceBaseUrl }), [voiceBaseUrl])
  return (
    <RuntimeConfigContext.Provider value={runtime}>
      <SystemConfigProvider>{children}</SystemConfigProvider>
    </RuntimeConfigContext.Provider>
  )
}
