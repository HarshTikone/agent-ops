import { useEffect, useState } from 'react'
import { fetchReadiness, type ReadinessResponse } from '../lib/api'

type Status =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'ready'; data: ReadinessResponse }

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
      .then((data) => setStatus({ state: 'ready', data }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        const message = err instanceof Error ? err.message : 'Unknown error'
        setStatus({ state: 'error', message })
      })
    return () => controller.abort()
  }, [])

  if (status.state === 'loading') {
    return (
      <p role="status" className="text-sm text-neutral-400">
        Checking backend connection…
      </p>
    )
  }

  if (status.state === 'error') {
    return (
      <p role="alert" className="text-sm text-red-500">
        Backend unreachable: {status.message}
      </p>
    )
  }

  const notConfigured = Object.entries(status.data.checks).filter(([, ok]) => !ok)

  return (
    <div className="text-sm">
      <p className={status.data.status === 'ready' ? 'text-green-500' : 'text-amber-500'}>
        Backend status: {status.data.status}
      </p>
      {notConfigured.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-amber-500">
          {notConfigured.map(([key]) => (
            <li key={key}>{key} missing</li>
          ))}
        </ul>
      )}
    </div>
  )
}
