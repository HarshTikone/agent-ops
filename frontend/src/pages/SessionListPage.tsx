import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  archiveSession,
  createSession,
  listSessions,
  restoreSession,
  type Session,
} from '../lib/api'
import { SessionList } from '../components/SessionList'
import { PlusIcon } from '../components/icons'

type LoadState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'loaded'; sessions: Session[] }

export function SessionListPage() {
  const [load, setLoad] = useState<LoadState>({ state: 'loading' })
  const [creating, setCreating] = useState(false)
  const [creatingSlow, setCreatingSlow] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [coldStart, setColdStart] = useState(false)
  const [loadVersion, setLoadVersion] = useState(0)
  const [showArchived, setShowArchived] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const activeCreate = useRef<AbortController | null>(null)
  const createSlowTimer = useRef<number | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => setColdStart(true), 8_000)
    listSessions(controller.signal, showArchived)
      .then((sessions) => setLoad({ state: 'loaded', sessions }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setLoad({ state: 'error', message: err instanceof Error ? err.message : 'Unknown error' })
      })
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [loadVersion, showArchived])

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

  // Archiving is server-side and shared across every device (ADR-030) —
  // replaces a prior per-device localStorage hide that could never clean
  // the list for anyone else. Update the loaded list in place rather than
  // refetching: an archived session simply drops out of view when
  // `showArchived` is off, or picks up its "Archived" badge when it's on.
  const handleArchive = (sessionId: string) => {
    setActionError(null)
    archiveSession(sessionId)
      .then((updated) => {
        setLoad((current) => {
          if (current.state !== 'loaded') return current
          const sessions = showArchived
            ? current.sessions.map((s) => (s.id === sessionId ? updated : s))
            : current.sessions.filter((s) => s.id !== sessionId)
          return { ...current, sessions }
        })
      })
      .catch((err: unknown) => {
        setActionError(err instanceof Error ? err.message : 'Could not archive this session')
      })
  }

  const handleRestore = (sessionId: string) => {
    setActionError(null)
    restoreSession(sessionId)
      .then((updated) => {
        setLoad((current) => {
          if (current.state !== 'loaded') return current
          const sessions = current.sessions.map((s) => (s.id === sessionId ? updated : s))
          return { ...current, sessions }
        })
      })
      .catch((err: unknown) => {
        setActionError(err instanceof Error ? err.message : 'Could not restore this session')
      })
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
        <div className="flex flex-wrap gap-2">
          <Link to="/demo" className="btn btn-secondary">
            View guided demo
          </Link>
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

      <label className="mb-[var(--space-4)] flex w-fit items-center gap-[var(--space-2)] text-sm">
        <input
          type="checkbox"
          checked={showArchived}
          onChange={(e) => {
            setLoad({ state: 'loading' })
            setShowArchived(e.target.checked)
          }}
        />
        Show archived sessions
      </label>

      {actionError && (
        <p role="alert" className="mb-[var(--space-4)] text-sm text-[var(--color-danger)]">
          {actionError}
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

      {load.state === 'loaded' && (
        <SessionList sessions={load.sessions} onArchive={handleArchive} onRestore={handleRestore} />
      )}
    </main>
  )
}
