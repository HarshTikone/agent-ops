import { useEffect, useRef, useState } from 'react'
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
  const [creatingSlow, setCreatingSlow] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [coldStart, setColdStart] = useState(false)
  const [loadVersion, setLoadVersion] = useState(0)
  const [hiddenSessionIds, setHiddenSessionIds] = useState(readHiddenSessionIds)
  const [hiddenNotice, setHiddenNotice] = useState<Session | null>(null)
  const activeCreate = useRef<AbortController | null>(null)
  const createSlowTimer = useRef<number | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => setColdStart(true), 8_000)
    listSessions(controller.signal)
      .then((sessions) => setLoad({ state: 'loaded', sessions }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setLoad({ state: 'error', message: err instanceof Error ? err.message : 'Unknown error' })
      })
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [loadVersion])

  useEffect(
    () => () => {
      activeCreate.current?.abort()
      if (createSlowTimer.current !== null) window.clearTimeout(createSlowTimer.current)
    },
    [],
  )

  const handleNewSession = () => {
    setCreating(true)
    setCreatingSlow(false)
    setCreateError(null)
    const controller = new AbortController()
    activeCreate.current = controller
    createSlowTimer.current = window.setTimeout(() => setCreatingSlow(true), 10_000)
    createSession(controller.signal)
      .then((session) => {
        if (controller.signal.aborted) return
        if (createSlowTimer.current !== null) window.clearTimeout(createSlowTimer.current)
        createSlowTimer.current = null
        activeCreate.current = null
        navigate(`/sessions/${session.id}`)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if (createSlowTimer.current !== null) window.clearTimeout(createSlowTimer.current)
        createSlowTimer.current = null
        activeCreate.current = null
        setCreateError(err instanceof Error ? err.message : 'Unknown error')
        setCreating(false)
        setCreatingSlow(false)
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

      {creatingSlow && (
        <p role="status" className="mb-[var(--space-4)] text-sm text-[var(--color-warning)]">
          Still creating the session. Do not retry yet; the server may still complete it.
        </p>
      )}

      {load.state === 'loading' && (
        <div role="status" className="text-muted text-sm">
          <p>Loading sessions…</p>
          {coldStart && (
            <p className="mt-2">The free backend may need about a minute to wake up.</p>
          )}
        </div>
      )}

      {load.state === 'error' && (
        <div role="alert" className="text-sm text-[var(--color-danger)]">
          <p>Could not load sessions: {load.message}</p>
          <button
            type="button"
            onClick={() => {
              setLoad({ state: 'loading' })
              setColdStart(false)
              setLoadVersion((version) => version + 1)
            }}
            className="btn btn-secondary mt-3"
          >
            Retry
          </button>
        </div>
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
