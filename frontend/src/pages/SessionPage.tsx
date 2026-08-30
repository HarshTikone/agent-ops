import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  approvePendingAction,
  getSession,
  getTrace,
  isValidSessionId,
  rejectPendingAction,
  sendMessage,
  type Session,
  type TraceEvent,
} from '../lib/api'
import { ApprovalModal, type ApprovalSubmission } from '../components/ApprovalModal'
import { ChatPanel } from '../components/ChatPanel'
import { ArrowLeftIcon } from '../components/icons'
import { StatusBadge } from '../components/StatusBadge'
import { TraceViewer } from '../components/TraceViewer'

type LoadState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'loaded'; session: Session; trace: TraceEvent[]; traceError: string | null }

type ActionKind = 'message' | 'approve' | 'reject' | null

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function SessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [load, setLoad] = useState<LoadState>({ state: 'loading' })
  const [actionKind, setActionKind] = useState<ActionKind>(null)
  const [messageError, setMessageError] = useState<string | null>(null)
  const [decisionError, setDecisionError] = useState<string | null>(null)
  const [coldStart, setColdStart] = useState(false)
  const [loadVersion, setLoadVersion] = useState(0)
  const [slowPhase, setSlowPhase] = useState<'slow' | 'very-slow' | null>(null)
  const activeAction = useRef<AbortController | null>(null)
  const activeActionTimers = useRef<number[]>([])

  useEffect(() => {
    if (!sessionId || !isValidSessionId(sessionId)) return
    const controller = new AbortController()
    const coldStartTimer = window.setTimeout(() => setColdStart(true), 8_000)
    getSession(sessionId, controller.signal)
      .then(async (session) => {
        try {
          const trace = await getTrace(sessionId, controller.signal)
          if (!controller.signal.aborted) {
            setLoad({ state: 'loaded', session, trace, traceError: null })
          }
        } catch (error) {
          if (isAbortError(error) || controller.signal.aborted) return
          setLoad({
            state: 'loaded',
            session,
            trace: [],
            traceError: error instanceof Error ? error.message : 'Unknown trace error',
          })
        }
      })
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        setLoad({
          state: 'error',
          message: error instanceof Error ? error.message : 'Unknown error',
        })
      })
    return () => {
      window.clearTimeout(coldStartTimer)
      controller.abort()
    }
  }, [loadVersion, sessionId])

  useEffect(
    () => () => {
      activeAction.current?.abort()
      activeActionTimers.current.forEach((timer) => window.clearTimeout(timer))
      activeActionTimers.current = []
    },
    [sessionId],
  )

  // The mutation response is the canonical session transition. Trace refresh
  // is separate so a failed read cannot resurrect a stale approval modal.
  const runAction = (
    kind: Exclude<ActionKind, null>,
    action: (signal: AbortSignal) => Promise<Session>,
  ) => {
    if (!sessionId || !isValidSessionId(sessionId)) return
    const actionSessionId = sessionId
    activeAction.current?.abort()
    activeActionTimers.current.forEach((timer) => window.clearTimeout(timer))
    const controller = new AbortController()
    activeAction.current = controller
    setActionKind(kind)
    if (kind === 'message') setMessageError(null)
    else setDecisionError(null)

    setSlowPhase(null)
    const slowTimer = window.setTimeout(() => setSlowPhase('slow'), 10_000)
    const verySlowTimer = window.setTimeout(() => setSlowPhase('very-slow'), 45_000)
    activeActionTimers.current = [slowTimer, verySlowTimer]

    action(controller.signal)
      .then((session) => {
        if (controller.signal.aborted) return
        setLoad((current) => ({
          state: 'loaded',
          session,
          trace: current.state === 'loaded' ? current.trace : [],
          traceError: null,
        }))
        return getTrace(actionSessionId, controller.signal)
          .then((trace) => {
            if (controller.signal.aborted) return
            setLoad((current) =>
              current.state === 'loaded' ? { ...current, trace, traceError: null } : current,
            )
          })
          .catch((error: unknown) => {
            if (isAbortError(error) || controller.signal.aborted) return
            setLoad((current) =>
              current.state === 'loaded'
                ? {
                    ...current,
                    traceError: error instanceof Error ? error.message : 'Unknown trace error',
                  }
                : current,
            )
          })
      })
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        const message = error instanceof Error ? error.message : 'Unknown error'
        if (kind === 'message') setMessageError(message)
        else setDecisionError(message)
      })
      .finally(() => {
        window.clearTimeout(slowTimer)
        window.clearTimeout(verySlowTimer)
        if (controller.signal.aborted || activeAction.current !== controller) return
        activeAction.current = null
        activeActionTimers.current = []
        setActionKind(null)
        setSlowPhase(null)
      })
  }

  if (!sessionId) {
    return (
      <p role="alert" className="p-[var(--space-8)] text-sm text-[var(--color-danger)]">
        No session id in the URL.
      </p>
    )
  }

  if (!isValidSessionId(sessionId)) {
    return (
      <main className="mx-auto w-full max-w-[720px] px-[var(--space-6)] py-[var(--space-8)]">
        <h1>Invalid session link</h1>
        <p role="alert" className="text-muted mt-2 text-sm">
          This URL does not contain a valid session identifier.
        </p>
        <Link to="/" className="btn btn-primary mt-[var(--space-4)]">
          Return to sessions
        </Link>
      </main>
    )
  }

  const approvalSubmission: ApprovalSubmission =
    actionKind === 'approve' || actionKind === 'reject' ? actionKind : null

  return (
    <main className="mx-auto flex w-full max-w-[1120px] flex-col px-[var(--space-6)] py-[var(--space-8)]">
      <Link to="/" className="btn btn-ghost mb-[var(--space-4)] self-start pl-0">
        <ArrowLeftIcon />
        All sessions
      </Link>

      {load.state === 'loading' && (
        <div role="status" className="text-muted text-sm">
          <p>Loading session…</p>
          {coldStart && (
            <p className="mt-2">The free backend may be waking up. This can take about a minute.</p>
          )}
        </div>
      )}

      {load.state === 'error' && (
        <div role="alert" className="text-sm text-[var(--color-danger)]">
          <p>Could not load this session: {load.message}</p>
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
        <>
          <div className="mb-[var(--space-6)] flex flex-wrap items-baseline justify-between gap-[var(--space-3)]">
            <div>
              <h1>Session</h1>
              <p className="text-muted mt-1 text-xs tracking-[0.04em]">
                SESSION · {load.session.id.slice(-4).toUpperCase()}
              </p>
            </div>
            <StatusBadge status={load.session.status} className="px-3 py-[5px] text-xs" />
          </div>

          <section aria-label="Chat" className="mb-[var(--space-8)]">
            <ChatPanel
              session={load.session}
              onSendMessage={(content) =>
                runAction('message', (signal) => sendMessage(sessionId, content, signal))
              }
              submitting={actionKind === 'message'}
              error={messageError}
            />
          </section>

          <section
            aria-label="Trace"
            className="border-t border-[var(--color-divider)] pt-[var(--space-4)]"
          >
            <h2 className="text-muted mb-[var(--space-4)] text-xs tracking-[0.08em] uppercase">
              Trace
            </h2>
            <TraceViewer events={load.trace} />
            {load.traceError && (
              <div role="alert" className="mt-3 text-sm text-[var(--color-danger)]">
                <p>Could not refresh the trace: {load.traceError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setLoad({ state: 'loading' })
                    setColdStart(false)
                    setLoadVersion((version) => version + 1)
                  }}
                  className="btn btn-secondary mt-2"
                >
                  Retry session data
                </button>
              </div>
            )}
          </section>

          {actionKind && slowPhase && (
            <p role="status" className="mt-4 text-sm text-[var(--color-warning)]">
              {slowPhase === 'very-slow'
                ? 'This is taking longer than expected. The server may still complete it; if you leave, refresh the session before trying again.'
                : 'Still working… provider requests can take a little while.'}
            </p>
          )}

          {load.session.pending_action && (
            <ApprovalModal
              key={load.session.pending_action.id}
              pendingAction={load.session.pending_action}
              onApprove={() =>
                runAction('approve', (signal) =>
                  approvePendingAction(load.session.pending_action!.id, signal),
                )
              }
              onReject={(reason) =>
                runAction('reject', (signal) =>
                  rejectPendingAction(load.session.pending_action!.id, reason, signal),
                )
              }
              submission={approvalSubmission}
              error={decisionError}
            />
          )}
        </>
      )}
    </main>
  )
}
