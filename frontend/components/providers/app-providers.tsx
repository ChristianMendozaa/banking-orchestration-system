"use client"

import { AuthProvider } from "@/components/providers/auth-provider"
import { SystemConfigProvider } from "@/components/providers/system-config-provider"

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <SystemConfigProvider>
      <AuthProvider>{children}</AuthProvider>
    </SystemConfigProvider>
  )
}
