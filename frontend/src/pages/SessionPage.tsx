import { useCallback, useEffect, useRef, useState } from 'react'
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
import { ApprovalModal, type ApprovalSubmission } from '../components/ApprovalModal'
import { ChatPanel } from '../components/ChatPanel'
import { ArrowLeftIcon } from '../components/icons'
import { StatusBadge } from '../components/StatusBadge'
import { TraceViewer } from '../components/TraceViewer'

type LoadState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'loaded'; session: Session; trace: TraceEvent[] }

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
  const activeAction = useRef<AbortController | null>(null)

  const refetch = useCallback(
    (signal?: AbortSignal) => {
      if (!sessionId) return
      return Promise.all([getSession(sessionId, signal), getTrace(sessionId, signal)]).then(
        ([session, trace]) => {
          if (!signal?.aborted) setLoad({ state: 'loaded', session, trace })
        },
      )
    },
    [sessionId],
  )

  useEffect(() => {
    if (!sessionId) return
    const controller = new AbortController()
    refetch(controller.signal)?.catch((error: unknown) => {
      if (isAbortError(error) || controller.signal.aborted) return
      setLoad({
        state: 'error',
        message: error instanceof Error ? error.message : 'Unknown error',
      })
    })
    return () => controller.abort()
  }, [refetch, sessionId])

  useEffect(
    () => () => {
      activeAction.current?.abort()
    },
    [],
  )

  // The action response deliberately is not trusted for trace state. Once a
  // mutation succeeds, session and trace are fetched together with the same
  // abort signal so unmounting cannot update a dead page.
  const runAction = (
    kind: Exclude<ActionKind, null>,
    action: (signal: AbortSignal) => Promise<Session>,
  ) => {
    activeAction.current?.abort()
    const controller = new AbortController()
    activeAction.current = controller
    setActionKind(kind)
    if (kind === 'message') setMessageError(null)
    else setDecisionError(null)

    action(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) return refetch(controller.signal)
      })
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        const message = error instanceof Error ? error.message : 'Unknown error'
        if (kind === 'message') setMessageError(message)
        else setDecisionError(message)
      })
      .finally(() => {
        if (controller.signal.aborted || activeAction.current !== controller) return
        activeAction.current = null
        setActionKind(null)
      })
  }

  if (!sessionId) {
    return (
      <p role="alert" className="p-[var(--space-8)] text-sm text-[var(--color-danger)]">
        No session id in the URL.
      </p>
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
        <p role="status" className="text-muted text-sm">
          Loading session…
        </p>
      )}

      {load.state === 'error' && (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          Could not load this session: {load.message}
        </p>
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
          </section>

          {load.session.pending_action && (
            <ApprovalModal
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
