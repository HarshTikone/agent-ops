import { useEffect, useState } from 'react'
import { fetchReadiness, type ReadinessResponse } from '../lib/api'

// 'loaded', not 'ready' — the backend's OWN status value is also literally
// "ready" (ReadinessResponse.status), and reusing the word here to mean
// "the fetch resolved" shadowed that in a way that read confusingly next to
// each other (flagged Day 1, fixed here alongside the rest of Day 4's UI).
type Status =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'loaded'; data: ReadinessResponse }

const readinessLabels: Record<keyof ReadinessResponse['checks'], string> = {
  gemini_api_key_set: 'Gemini API key',
  openrouter_api_key_set: 'OpenRouter API key',
  supabase_configured: 'Supabase',
  database_configured: 'Database configuration',
  database_reachable: 'Database connection',
}

/**
 * Minimal, real connectivity check against the backend's /health/ready
 * endpoint. Deliberately covers all three states (loading/error/success),
 * not just the happy path — this is the pattern the Day 4 chat UI, trace
 * viewer, and approval modal all reuse for their own API calls.
 */
export function BackendStatus() {
  const [status, setStatus] = useState<Status>({ state: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    fetchReadiness(controller.signal)
      .then((data) => setStatus({ state: 'loaded', data }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        const message = err instanceof Error ? err.message : 'Unknown error'
        setStatus({ state: 'error', message })
      })
    return () => controller.abort()
  }, [])

  if (status.state === 'loading') {
    return (
      <p role="status" className="text-muted text-sm">
        Checking backend connection…
      </p>
    )
  }

  if (status.state === 'error') {
    return (
      <p role="alert" className="text-sm text-[var(--color-danger)]">
        Backend unreachable: {status.message}
      </p>
    )
  }

  const notConfigured = Object.entries(status.data.checks).filter(([, ok]) => !ok)

  // Three-way, not binary: "degraded" can still serve every request (Gemini
  // + Supabase + database are all present — only the OpenRouter failover
  // safety net is missing), so it reads as a distinct warning color, not
  // the same red as a genuinely broken "not_ready" deploy. See ADR-009.
  const statusColor: Record<typeof status.data.status, string> = {
    ready: 'text-[var(--color-success)]',
    degraded: 'text-[var(--color-warning)]',
    not_ready: 'text-[var(--color-danger)]',
  }

  return (
    <div className="text-sm">
      <p className={statusColor[status.data.status]}>Backend status: {status.data.status}</p>
      {notConfigured.length > 0 && (
        <ul className={`mt-1 list-disc pl-5 ${statusColor[status.data.status]}`}>
          {notConfigured.map(([key]) => (
            <li key={key}>{readinessLabels[key as keyof ReadinessResponse['checks']]} missing</li>
          ))}
        </ul>
      )}
    </div>
  )
}
