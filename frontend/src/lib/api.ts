/**
 * Base API config. The frontend never talks to Gemini/OpenRouter/Supabase
 * directly — only to our own backend, which holds every secret.
 */

export const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface ReadinessChecks {
  gemini_api_key_set: boolean
  openrouter_api_key_set: boolean
  supabase_configured: boolean
  database_configured: boolean
}

/**
 * Per ADR-009: "ready" (fully configured), "degraded" (Gemini + Supabase +
 * database all present, so every request can be served — but no OpenRouter
 * key, so there's no failover safety net if Gemini has an outage), or
 * "not_ready" (missing something the system cannot serve anything without
 * at all).
 */
export interface ReadinessResponse {
  status: 'ready' | 'degraded' | 'not_ready'
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

// --- Sessions / messages / trace / approvals (Day 3 backend, Day 4 UI) ----

/**
 * Mirrors sessions.status's CHECK constraint (ADR-015): 'created' (just
 * made, no task yet) -> 'running' (mid-graph, only ever observed WITHIN a
 * request/response cycle since every mutating call is synchronous) ->
 * 'awaiting_approval' (paused on an irreversible step, ADR-016) <->
 * 'running' again on resume -> 'done' | 'failed'.
 */
export type SessionStatus = 'created' | 'running' | 'awaiting_approval' | 'done' | 'failed'

export interface PendingAction {
  id: string
  session_id: string
  tool_name: string
  tool_args: Record<string, unknown>
  status: 'pending' | 'approved' | 'rejected' | 'executed'
  reason: string | null
  created_at: string
  decided_at: string | null
}

/**
 * `pending_action` is populated only when `status === 'awaiting_approval'`
 * (ADR-018) — the approval modal's entire data need in one fetch.
 */
export interface Session {
  id: string
  task: string
  status: SessionStatus
  final_answer: string | null
  created_at: string
  updated_at: string
  pending_action: PendingAction | null
}

export interface TraceEvent {
  id: number
  session_id: string
  node: string
  detail: string
  provider: string | null
  created_at: string
}

/**
 * Shared request helper: on a non-2xx response, prefers FastAPI's
 * `{"detail": "..."}` body (a real, specific reason — "session is
 * 'awaiting_approval', not 'created'") over a generic status-code message,
 * since every mutating endpoint below can return a meaningful 404/409.
 */
async function request<T>(path: string, init?: RequestInit & { signal?: AbortSignal }): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let detail = `request to ${path} failed with status ${response.status}`
    try {
      const body: unknown = await response.json()
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // response wasn't JSON — fall back to the generic message above
    }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

export function createSession(signal?: AbortSignal): Promise<Session> {
  return request<Session>('/sessions', { method: 'POST', signal })
}

export function listSessions(signal?: AbortSignal): Promise<Session[]> {
  return request<Session[]>('/sessions', { signal })
}

export function getSession(sessionId: string, signal?: AbortSignal): Promise<Session> {
  return request<Session>(`/sessions/${sessionId}`, { signal })
}

export function getTrace(sessionId: string, signal?: AbortSignal): Promise<TraceEvent[]> {
  return request<TraceEvent[]>(`/sessions/${sessionId}/trace`, { signal })
}

/** Blocks until the graph either finishes or pauses on an approval —
 * ARCHITECTURE.md §3 step 5: the run ends synchronously within this call,
 * it isn't held open server-side, so this can genuinely take several
 * seconds for a real Gemini call and callers must show a loading state. */
export function sendMessage(
  sessionId: string,
  content: string,
  signal?: AbortSignal,
): Promise<Session> {
  return request<Session>(`/sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
    signal,
  })
}

export function approvePendingAction(
  pendingActionId: string,
  signal?: AbortSignal,
): Promise<Session> {
  return request<Session>(`/approvals/${pendingActionId}/approve`, { method: 'POST', signal })
}

export function rejectPendingAction(
  pendingActionId: string,
  reason?: string,
  signal?: AbortSignal,
): Promise<Session> {
  return request<Session>(`/approvals/${pendingActionId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason ?? null }),
    signal,
  })
}
