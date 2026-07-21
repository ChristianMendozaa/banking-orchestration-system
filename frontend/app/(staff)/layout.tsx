import { AuthProvider } from "@/components/providers/auth-provider"

export default function StaffLayout({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}
