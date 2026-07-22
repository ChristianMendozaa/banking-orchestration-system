"use client"

import { apiDownload, apiRequest, ApiError } from "@/lib/api"
import type { TokenResponse, User, UserRole } from "@/lib/types"
import { useRouter } from "next/navigation"
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  logout: () => Promise<void>
  request: <T>(path: string, init?: RequestInit) => Promise<T>
  download: (path: string) => Promise<{ blob: Blob; fileName: string }>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const tokenRef = useRef<string | null>(null)
  const refreshPromiseRef = useRef<Promise<TokenResponse> | null>(null)
  const initialized = useRef(false)

  const applySession = useCallback((session: TokenResponse | null) => {
    tokenRef.current = session?.access_token ?? null
    setUser(session?.user ?? null)
  }, [])

  const refresh = useCallback(async (): Promise<TokenResponse> => {
    if (refreshPromiseRef.current) return refreshPromiseRef.current
    const pending = apiRequest<TokenResponse>("/auth/refresh", { method: "POST" }).then(
      (session) => {
        applySession(session)
        return session
      },
    )
    refreshPromiseRef.current = pending
    try {
      return await pending
    } finally {
      if (refreshPromiseRef.current === pending) refreshPromiseRef.current = null
    }
  }, [applySession])

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true
    void refresh()
      .catch(() => applySession(null))
      .finally(() => setLoading(false))
  }, [applySession, refresh])

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await apiRequest<TokenResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      })
      applySession(session)
      return session.user
    },
    [applySession],
  )

  const logout = useCallback(async () => {
    try {
      await apiRequest<void>("/auth/logout", { method: "POST" })
    } finally {
      applySession(null)
    }
  }, [applySession])

  const request = useCallback(
    async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
      try {
        return await apiRequest<T>(path, init, tokenRef.current)
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error
        const session = await refresh()
        return apiRequest<T>(path, init, session.access_token)
      }
    },
    [refresh],
  )

  const download = useCallback(
    async (path: string) => {
      try {
        if (!tokenRef.current) throw new ApiError(401, { message: "Sesión no disponible" })
        return await apiDownload(path, tokenRef.current)
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error
        const session = await refresh()
        return apiDownload(path, session.access_token)
      }
    },
    [refresh],
  )

  const value = useMemo(
    () => ({ user, loading, login, logout, request, download }),
    [user, loading, login, logout, request, download],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error("useAuth debe utilizarse dentro de AuthProvider")
  return value
}

export function RoleGuard({
  roles,
  children,
}: {
  roles: UserRole[]
  children: React.ReactNode
}) {
  const { user, loading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (loading) return
    if (!user) router.replace("/login")
    else if (!roles.includes(user.role)) {
      router.replace(user.role === "MANAGER" ? "/gerencial" : "/ejecutivo")
    }
  }, [loading, roles, router, user])

  if (loading || !user || !roles.includes(user.role)) {
    return (
      <div className="grid min-h-screen place-items-center bg-gray-100" role="status">
        <p className="text-sm text-gray-500">Validando acceso…</p>
      </div>
    )
  }
  return children
}
