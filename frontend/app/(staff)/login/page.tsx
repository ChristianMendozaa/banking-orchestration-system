"use client"

import { useAuth } from "@/components/providers/auth-provider"
import { Button } from "@/components/ui/button"
import { errorMessage } from "@/lib/api"
import { Building2, Eye, EyeOff } from "lucide-react"
import { useRouter } from "next/navigation"
import { FormEvent, useEffect, useState } from "react"

export default function LoginPage() {
  const { login, user, loading } = useAuth()
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!loading && user) {
      router.replace(user.role === "MANAGER" ? "/gerencial" : "/ejecutivo")
    }
  }, [loading, router, user])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const authenticated = await login(email.trim(), password)
      router.replace(authenticated.role === "MANAGER" ? "/gerencial" : "/ejecutivo")
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[#071426] p-6" id="main-content">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-white p-8 shadow-2xl">
        <div className="mb-8 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-[#1168BD]">
            <Building2 className="h-6 w-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Acceso del personal</h1>
            <p className="text-sm text-gray-500">Sistema de orquestación</p>
          </div>
        </div>

        <form className="space-y-5" onSubmit={handleSubmit}>
          <label className="block text-sm font-medium text-gray-700">
            Correo
            <input
              autoComplete="username"
              className="mt-2 w-full rounded-xl border border-gray-200 px-4 py-3 outline-none focus:border-[#1168BD] focus:ring-2 focus:ring-[#1168BD]/20"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label className="block text-sm font-medium text-gray-700">
            Contraseña
            <span className="relative mt-2 block">
              <input
                autoComplete="current-password"
                className="w-full rounded-xl border border-gray-200 px-4 py-3 pr-12 outline-none focus:border-[#1168BD] focus:ring-2 focus:ring-[#1168BD]/20"
                minLength={8}
                onChange={(event) => setPassword(event.target.value)}
                required
                type={showPassword ? "text" : "password"}
                value={password}
              />
              <button
                aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500"
                onClick={() => setShowPassword((current) => !current)}
                type="button"
              >
                {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
              </button>
            </span>
          </label>
          {error && (
            <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700" role="alert">
              {error}
            </p>
          )}
          <Button className="w-full" disabled={submitting || loading} size="lg" type="submit">
            {submitting ? "Ingresando…" : "Ingresar"}
          </Button>
        </form>
      </div>
    </main>
  )
}
