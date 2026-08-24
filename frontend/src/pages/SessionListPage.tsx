import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSession, listSessions, type Session } from '../lib/api'
import { SessionList } from '../components/SessionList'

type LoadState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'loaded'; sessions: Session[] }

export function SessionListPage() {
  const [load, setLoad] = useState<LoadState>({ state: 'loading' })
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const controller = new AbortController()
    listSessions(controller.signal)
      .then((sessions) => setLoad({ state: 'loaded', sessions }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setLoad({ state: 'error', message: err instanceof Error ? err.message : 'Unknown error' })
      })
    return () => controller.abort()
  }, [])

  const handleNewSession = () => {
    setCreating(true)
    setCreateError(null)
    createSession()
      .then((session) => navigate(`/sessions/${session.id}`))
      .catch((err: unknown) => {
        setCreateError(err instanceof Error ? err.message : 'Unknown error')
        setCreating(false)
      })
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-neutral-100">Sessions</h1>
        <button
          type="button"
          onClick={handleNewSession}
          disabled={creating}
          className="rounded bg-blue-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
        >
          {creating ? 'Creating…' : 'New session'}
        </button>
      </div>

      {createError && (
        <p role="alert" className="text-sm text-red-400">
          Could not create a session: {createError}
        </p>
      )}

      {load.state === 'loading' && (
        <p role="status" className="text-sm text-neutral-400">
          Loading sessions…
        </p>
      )}

      {load.state === 'error' && (
        <p role="alert" className="text-sm text-red-500">
          Could not load sessions: {load.message}
        </p>
      )}

      {load.state === 'loaded' && <SessionList sessions={load.sessions} />}
    </div>
  )
}
