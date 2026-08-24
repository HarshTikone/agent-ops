import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  approvePendingAction,
  getSession,
  getTrace,
  rejectPendingAction,
  sendMessage,
  type Session,
  type TraceEvent,
} from '../lib/api'
import { ApprovalModal } from '../components/ApprovalModal'
import { ChatPanel } from '../components/ChatPanel'
import { StatusBadge } from '../components/StatusBadge'
import { TraceViewer } from '../components/TraceViewer'

type LoadState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'loaded'; session: Session; trace: TraceEvent[] }

export function SessionPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [load, setLoad] = useState<LoadState>({ state: 'loading' })
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const refetch = useCallback(
    (signal?: AbortSignal) => {
      if (!sessionId) return
      return Promise.all([getSession(sessionId, signal), getTrace(sessionId, signal)]).then(
        ([session, trace]) => setLoad({ state: 'loaded', session, trace }),
      )
    },
    [sessionId],
  )

  useEffect(() => {
    if (!sessionId) return
    const controller = new AbortController()
    // No setLoad({state: 'loading'}) reset here on purpose: SessionPage is
    // remounted (via `key={sessionId}` where it's routed, see App.tsx)
    // whenever the id changes, so useState's initializer already starts
    // each mount at 'loading' — resetting it again mid-effect would be the
    // exact synchronous-setState-in-effect antipattern the react-hooks
    // lint rule flags, and would also leave stale submitting/actionError
    // state from a PREVIOUS session bleeding into the next one's view.
    refetch(controller.signal)?.catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setLoad({ state: 'error', message: err instanceof Error ? err.message : 'Unknown error' })
    })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch is stable per sessionId
  }, [sessionId])

  // After every mutating action, re-fetch session + trace rather than
  // trust the action's own response for the trace: the backend only
  // returns the SESSION from these calls (ADR-018), and the trace grows
  // with every node the run touched, which the frontend can't reconstruct.
  const runAction = (action: () => Promise<Session>) => {
    setSubmitting(true)
    setActionError(null)
    action()
      .then(() => refetch())
      .catch((err: unknown) => {
        setActionError(err instanceof Error ? err.message : 'Unknown error')
      })
      .finally(() => setSubmitting(false))
  }

  if (!sessionId) {
    return (
      <p role="alert" className="p-8 text-sm text-red-500">
        No session id in the URL.
      </p>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
      <Link to="/" className="text-sm text-neutral-400 hover:text-neutral-200">
        ← All sessions
      </Link>

      {load.state === 'loading' && (
        <p role="status" className="text-sm text-neutral-400">
          Loading session…
        </p>
      )}

      {load.state === 'error' && (
        <p role="alert" className="text-sm text-red-500">
          Could not load this session: {load.message}
        </p>
      )}

      {load.state === 'loaded' && (
        <>
          <div className="flex items-center justify-between">
            <h1 className="text-xl font-semibold text-neutral-100">Session</h1>
            <StatusBadge status={load.session.status} />
          </div>

          <section aria-label="Chat">
            <ChatPanel
              session={load.session}
              onSendMessage={(content) => runAction(() => sendMessage(sessionId, content))}
              submitting={submitting}
              error={load.session.pending_action ? null : actionError}
            />
          </section>

          <section aria-label="Trace" className="border-t border-neutral-800 pt-4">
            <h2 className="mb-2 text-sm font-medium text-neutral-400">Trace</h2>
            <TraceViewer events={load.trace} />
          </section>

          {load.session.pending_action && (
            <ApprovalModal
              pendingAction={load.session.pending_action}
              onApprove={() =>
                runAction(() => approvePendingAction(load.session.pending_action!.id))
              }
              onReject={(reason) =>
                runAction(() => rejectPendingAction(load.session.pending_action!.id, reason))
              }
              submitting={submitting}
              error={actionError}
            />
          )}
        </>
      )}
    </div>
  )
}
