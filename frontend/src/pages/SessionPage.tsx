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
      <p role="alert" className="p-8 text-sm text-red-500">
        No session id in the URL.
      </p>
    )
  }

  const approvalSubmission: ApprovalSubmission =
    actionKind === 'approve' || actionKind === 'reject' ? actionKind : null

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
              onSendMessage={(content) =>
                runAction('message', (signal) => sendMessage(sessionId, content, signal))
              }
              submitting={actionKind === 'message'}
              error={messageError}
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
    </div>
  )
}
