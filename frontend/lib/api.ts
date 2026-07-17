const API_ROOT = "/backend-api/api/v1"

export interface ApiErrorBody {
  code?: string
  message?: string
  details?: unknown
  trace_id?: string
}

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  traceId?: string

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || "No fue posible completar la solicitud")
    this.name = "ApiError"
    this.status = status
    this.code = body.code || "HTTP_ERROR"
    this.details = body.details
    this.traceId = body.trace_id
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody = {}
  try {
    body = (await response.json()) as ApiErrorBody
  } catch {
    body = { message: response.statusText }
  }
  return new ApiError(response.status, body)
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  accessToken?: string | null,
): Promise<T> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store",
  })
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function apiDownload(
  path: string,
  accessToken: string,
): Promise<{ blob: Blob; fileName: string }> {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    credentials: "include",
    cache: "no-store",
  })
  if (!response.ok) throw await parseError(response)
  const disposition = response.headers.get("content-disposition") || ""
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const basic = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  return {
    blob: await response.blob(),
    fileName: encoded ? decodeURIComponent(encoded) : basic || "documento.pdf",
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Ocurrió un error inesperado"
}
