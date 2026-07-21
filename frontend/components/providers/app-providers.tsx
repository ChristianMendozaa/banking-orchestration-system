"use client"

import { SystemConfigProvider } from "@/components/providers/system-config-provider"

export function AppProviders({ children }: { children: React.ReactNode }) {
  return <SystemConfigProvider>{children}</SystemConfigProvider>
}
