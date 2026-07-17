"use client"

import { apiRequest, errorMessage } from "@/lib/api"
import type { PublicSystemConfig } from "@/lib/types"
import { createContext, useContext, useEffect, useState } from "react"

interface SystemConfigContextValue {
  config: PublicSystemConfig | null
  loading: boolean
  error: string | null
}

const SystemConfigContext = createContext<SystemConfigContextValue | null>(null)

export function SystemConfigProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<PublicSystemConfig | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void apiRequest<PublicSystemConfig>("/system/public-config")
      .then(setConfig)
      .catch((reason) => setError(errorMessage(reason)))
      .finally(() => setLoading(false))
  }, [])

  return (
    <SystemConfigContext.Provider value={{ config, loading, error }}>
      {children}
    </SystemConfigContext.Provider>
  )
}

export function useSystemConfig(): SystemConfigContextValue {
  const value = useContext(SystemConfigContext)
  if (!value) throw new Error("useSystemConfig requiere SystemConfigProvider")
  return value
}
