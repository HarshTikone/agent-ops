import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSession, listSessions, type Session } from '../lib/api'
import { SessionList } from '../components/SessionList'
import { PlusIcon } from '../components/icons'

type LoadState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'loaded'; sessions: Session[] }

const HIDDEN_SESSIONS_STORAGE_KEY = 'agent-ops.hidden-sessions'

function readHiddenSessionIds(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(HIDDEN_SESSIONS_STORAGE_KEY) ?? '[]')
    return new Set(
      Array.isArray(parsed)
        ? parsed.filter((value): value is string => typeof value === 'string')
        : [],
    )
  } catch {
    return new Set()
  }
}

function persistHiddenSessionIds(ids: Set<string>): void {
  try {
    localStorage.setItem(HIDDEN_SESSIONS_STORAGE_KEY, JSON.stringify([...ids]))
  } catch {
    // Soft-hiding still works for this render when storage is unavailable.
  }
}

export function SessionListPage() {
  const [load, setLoad] = useState<LoadState>({ state: 'loading' })
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [hiddenSessionIds, setHiddenSessionIds] = useState(readHiddenSessionIds)
  const [hiddenNotice, setHiddenNotice] = useState<Session | null>(null)
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

  // The backend intentionally has no DELETE endpoint yet. Persist a local
  // soft-hide and make it undoable rather than pretending server data was
  // deleted. Replace this with an authenticated API call when one exists.
  const handleRemove = (sessionId: string) => {
    if (load.state === 'loaded') {
      setHiddenNotice(load.sessions.find((session) => session.id === sessionId) ?? null)
    }
    setHiddenSessionIds((current) => {
      const next = new Set(current).add(sessionId)
      persistHiddenSessionIds(next)
      return next
    })
  }

  const undoRemove = () => {
    if (!hiddenNotice) return
    setHiddenSessionIds((current) => {
      const next = new Set(current)
      next.delete(hiddenNotice.id)
      persistHiddenSessionIds(next)
      return next
    })
    setHiddenNotice(null)
  }

  const restoreHiddenSessions = () => {
    const next = new Set<string>()
    persistHiddenSessionIds(next)
    setHiddenSessionIds(next)
    setHiddenNotice(null)
  }

  return (
    <main className="mx-auto flex w-full max-w-[1120px] flex-col px-[var(--space-6)] py-[var(--space-8)]">
      <div className="mb-[var(--space-6)] flex flex-wrap items-end justify-between gap-[var(--space-4)]">
        <div>
          <h1>Sessions</h1>
          <p className="text-muted mt-1 text-sm">
            Every task the planner has run, with its full trace.
          </p>
        </div>
        <button
          type="button"
          onClick={handleNewSession}
          disabled={creating}
          className="btn btn-primary"
        >
          <PlusIcon />
          {creating ? 'Creating…' : 'New session'}
        </button>
      </div>

      {createError && (
        <p role="alert" className="mb-[var(--space-4)] text-sm text-[var(--color-danger)]">
          Could not create a session: {createError}
        </p>
      )}

      {load.state === 'loading' && (
        <p role="status" className="text-muted text-sm">
          Loading sessions…
        </p>
      )}

      {load.state === 'error' && (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          Could not load sessions: {load.message}
        </p>
      )}

      {hiddenSessionIds.size > 0 && (
        <div
          role="status"
          className="mb-[var(--space-4)] flex flex-wrap items-center gap-[var(--space-2)] text-sm"
        >
          <span>
            {hiddenNotice
              ? `Session ${hiddenNotice.id.slice(-4).toUpperCase()} is hidden on this device.`
              : `${hiddenSessionIds.size} session${hiddenSessionIds.size === 1 ? '' : 's'} hidden on this device.`}
          </span>
          {hiddenNotice && (
            <button type="button" onClick={undoRemove} className="btn btn-ghost px-2 py-1 text-xs">
              Undo
            </button>
          )}
          {(!hiddenNotice || hiddenSessionIds.size > 1) && (
            <button
              type="button"
              onClick={restoreHiddenSessions}
              className="btn btn-ghost px-2 py-1 text-xs"
            >
              Show all hidden sessions
            </button>
          )}
        </div>
      )}

      {load.state === 'loaded' && (
        <SessionList
          sessions={load.sessions.filter((session) => !hiddenSessionIds.has(session.id))}
          onRemove={handleRemove}
        />
      )}
    </main>
  )
}
