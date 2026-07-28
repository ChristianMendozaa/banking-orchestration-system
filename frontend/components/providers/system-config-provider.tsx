"use client"

import { apiRequest, errorMessage } from "@/lib/api"
import type { PublicSystemConfig } from "@/lib/types"
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"

interface SystemConfigContextValue {
  config: PublicSystemConfig | null
  loading: boolean
  error: string | null
  reload: () => Promise<void>
}

const SystemConfigContext = createContext<SystemConfigContextValue | null>(null)

export function SystemConfigProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<PublicSystemConfig | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setConfig(await apiRequest<PublicSystemConfig>("/system/public-config"))
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    queueMicrotask(() => void reload())
  }, [reload])

  const value = useMemo(
    () => ({ config, loading, error, reload }),
    [config, error, loading, reload],
  )
  return (
    <SystemConfigContext.Provider value={value}>
      {children}
    </SystemConfigContext.Provider>
  )
}

export function useSystemConfig(): SystemConfigContextValue {
  const value = useContext(SystemConfigContext)
  if (!value) throw new Error("useSystemConfig requiere SystemConfigProvider")
  return value
}
