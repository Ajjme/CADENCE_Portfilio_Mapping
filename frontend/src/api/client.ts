// What every backend call shares: where the backend is, and turning its error
// messages into errors a page can show. The calls themselves are in the other
// files in this folder.
import type { components } from './schema'

// The shapes the backend sends and receives, generated from its Python models
// (CADENCE/src/cadence/api/schemas.py). For example, Schemas['RunSummary'].
export type Schemas = components['schemas']

// While developing, Vite passes /api requests on to the backend (see
// vite.config.ts), so the address stays empty. A deployed frontend sets
// VITE_API_URL to wherever the backend runs.
const BASE_URL: string = import.meta.env.VITE_API_URL ?? ''

type QueryValue = string | number | undefined

// An error from the backend, with the message it sent back.
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// The full address for a backend path. Leaves out query values that are undefined.
export function apiUrl(path: string, query: Record<string, QueryValue> = {}) {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value))
  }
  const search = params.toString()
  return `${BASE_URL}${path}${search ? `?${search}` : ''}`
}

// Calls the backend and returns its JSON reply, or throws an ApiError.
export async function request<T>(
  path: string,
  options: RequestInit & { query?: Record<string, QueryValue> } = {},
): Promise<T> {
  const { query, ...init } = options
  const response = await fetch(apiUrl(path, query), init)
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return (await response.json()) as T
}

// Sends a JSON body with a POST.
export function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// The backend puts its message in `detail`. For a malformed request it's a
// list of problems instead, one per field.
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((problem: { msg?: string }) => problem.msg)
        .join('; ')
    }
  } catch {
    // Not JSON - fall through to the status line.
  }
  return `The backend answered ${response.status} ${response.statusText}`
}
