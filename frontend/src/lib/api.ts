/**
 * Base API config. The frontend never talks to Gemini/OpenRouter/Supabase
 * directly — only to our own backend, which holds every secret. Day 1 scope
 * is limited to the health check; session/message/approval/trace calls are
 * added Day 3-4 alongside their backend endpoints.
 */

export const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface ReadinessChecks {
  gemini_api_key_set: boolean
  openrouter_api_key_set: boolean
  supabase_configured: boolean
  database_configured: boolean
}

export interface ReadinessResponse {
  status: 'ready' | 'not_ready'
  checks: ReadinessChecks
}

/** Thrown when the backend responds but with a non-2xx status. */
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function fetchReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/health/ready`, { signal })
  if (!response.ok) {
    throw new ApiError(
      `Backend readiness check failed with status ${response.status}`,
      response.status,
    )
  }
  return response.json() as Promise<ReadinessResponse>
}
