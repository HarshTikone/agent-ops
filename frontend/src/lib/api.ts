/**
 * Base API config. The frontend never talks to Gemini/OpenRouter/Supabase
 * directly — only to our own backend, which holds every secret.
 */

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim()
if (import.meta.env.PROD && !configuredApiUrl) {
  throw new Error('VITE_API_URL is required for production builds')
}
export const API_BASE_URL = configuredApiUrl?.replace(/\/$/, '') ?? 'http://localhost:8000'
const OPERATOR_KEY_STORAGE = 'agent-ops.operator-key'
export const MIN_OPERATOR_KEY_BYTES = 32
const READ_TIMEOUT_MS = 30_000
const READ_RETRY_DELAY_MS = 2_000

export function operatorKeyByteLength(key: string): number {
  return new TextEncoder().encode(key.trim()).byteLength
}

export function getOperatorKey(): string {
  try {
    return sessionStorage.getItem(OPERATOR_KEY_STORAGE)?.trim() ?? ''
  } catch {
    // Storage can be unavailable in privacy-restricted contexts. Treat that
    // exactly like an unset runtime key instead of crashing the whole header.
    return ''
  }
}

export function setOperatorKey(key: string): boolean {
  const normalized = key.trim()
  try {
    if (normalized) sessionStorage.setItem(OPERATOR_KEY_STORAGE, normalized)
    else sessionStorage.removeItem(OPERATOR_KEY_STORAGE)
    return getOperatorKey() === normalized
  } catch {
    return false
  }
}

export function clearOperatorKey(): boolean {
  try {
    sessionStorage.removeItem(OPERATOR_KEY_STORAGE)
    return getOperatorKey() === ''
  } catch {
    return false
  }
}

export interface ReadinessChecks {
  gemini_api_key_set: boolean
  openrouter_api_key_set: boolean
  supabase_configured: boolean
  database_configured: boolean
  database_reachable: boolean
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

function abortError(): DOMException {
  return new DOMException('The request was aborted.', 'AbortError')
}

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError())
      return
    }
    const handleAbort = () => {
      window.clearTimeout(timer)
      reject(abortError())
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', handleAbort)
      resolve()
    }, milliseconds)
    signal?.addEventListener('abort', handleAbort, { once: true })
  })
}

async function fetchAttempt(url: string, init: RequestInit, timeout: boolean): Promise<Response> {
  if (!timeout) return fetch(url, init)

  if (init.signal?.aborted) throw abortError()
  const controller = new AbortController()
  let timedOut = false
  const parentSignal = init.signal
  const forwardAbort = () => controller.abort(parentSignal?.reason)
  parentSignal?.addEventListener('abort', forwardAbort, { once: true })
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, READ_TIMEOUT_MS)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch (error) {
    if (timedOut) throw new ApiError('Backend read timed out while the service was waking up.', 408)
    throw error
  } finally {
    window.clearTimeout(timer)
    parentSignal?.removeEventListener('abort', forwardAbort)
  }
}

function detailMessage(body: unknown): string | null {
  if (!body || typeof body !== 'object' || !('detail' in body)) return null
  if (typeof body.detail === 'string') return body.detail
  if (!Array.isArray(body.detail)) return null
  const messages = body.detail
    .map((item: unknown) => {
      if (!item || typeof item !== 'object' || !('msg' in item) || typeof item.msg !== 'string') {
        return null
      }
      return item.msg
    })
    .filter((message): message is string => Boolean(message))
  return messages.length > 0 ? `Invalid request: ${messages.join('; ')}` : null
}

export async function fetchReadiness(signal?: AbortSignal): Promise<ReadinessResponse> {
  return request<ReadinessResponse>('/health/ready', { signal })
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
  sequence: number
  node: string
  detail: string
  level: 'info' | 'success' | 'warning' | 'error'
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
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers = new Headers(init?.headers)
  if (init?.body) headers.set('Content-Type', 'application/json')
  if (method !== 'GET' && method !== 'HEAD') {
    const operatorKey = getOperatorKey()
    if (!operatorKey) {
      throw new ApiError('Enter the operator key before making changes.', 401)
    }
    if (operatorKeyByteLength(operatorKey) < MIN_OPERATOR_KEY_BYTES) {
      throw new ApiError('The operator key must contain at least 32 bytes.', 401)
    }
    headers.set('X-Agent-Ops-Key', operatorKey)
  }
  const requestInit = { ...init, headers }
  const mayRetry = method === 'GET' || method === 'HEAD'
  let response: Response | undefined
  let lastError: unknown
  const attempts = mayRetry ? 2 : 1
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      response = await fetchAttempt(`${API_BASE_URL}${path}`, requestInit, mayRetry)
      if (response.ok || response.status < 500 || attempt === attempts - 1) break
    } catch (error) {
      lastError = error
      if (init?.signal?.aborted || attempt === attempts - 1) throw error
    }
    await wait(READ_RETRY_DELAY_MS, init?.signal)
  }
  if (!response) throw lastError
  if (!response.ok) {
    let detail = `request to ${path} failed with status ${response.status}`
    try {
      const body: unknown = await response.json()
      detail = detailMessage(body) ?? detail
    } catch {
      // response wasn't JSON — fall back to the generic message above
    }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

export function isValidSessionId(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
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
