import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  approvePendingAction,
  getMessages,
  getSession,
  getTrace,
  isValidSessionId,
  rejectPendingAction,
  sendMessage,
  type Message,
  type Session,
  type TraceEvent,
} from '../lib/api'
import { ApprovalModal, type ApprovalSubmission } from '../components/ApprovalModal'
import { ChatPanel } from '../components/ChatPanel'
import { ArrowLeftIcon } from '../components/icons'
import { StatusBadge } from '../components/StatusBadge'
import { TraceViewer } from '../components/TraceViewer'
import { formatDuration } from '../lib/format'

/**
 * Run totals for the session header (P3): wall time is the SUM of each
 * timed node's own `duration_ms`, not `last.created_at - first.created_at`.
 * An approval pause can hold a session open for minutes of operator think
 * time between two trace rows — see `approval_gate_node`'s docstring — and
 * that gap must not be reported as agent latency. Untimed nodes simply
 * don't contribute, so the sum is exactly "time the agent itself spent
 * calling a provider or a tool."
 *
 * Each total renders "—", not 0, when nothing in the trace measured it —
 * distinguishing "not measured" from "measured as zero/free".
 */
function summarizeTrace(events: TraceEvent[]): {
  wallMs: number | null
  tokensTotal: number | null
  costUsd: number | null
} {
  const durations = events.map((e) => e.duration_ms).filter((v): v is number => v !== null)
  const tokenCounts = events
    .flatMap((e) => [e.tokens_in, e.tokens_out])
    .filter((v): v is number => v !== null)
  const costs = events.map((e) => e.cost_usd).filter((v): v is string => v !== null)

  return {
    wallMs: durations.length > 0 ? durations.reduce((sum, ms) => sum + ms, 0) : null,
    tokensTotal: tokenCounts.length > 0 ? tokenCounts.reduce((sum, n) => sum + n, 0) : null,
    costUsd: costs.length > 0 ? costs.reduce((sum, c) => sum + Number(c), 0) : null,
  }
}

function formatTokenTotal(tokens: number | null): string {
  return tokens === null ? '—' : tokens.toLocaleString()
}

function formatCostTotal(costUsd: number | null): string {
  if (costUsd === null) return '—'
  return `$${costUsd < 0.01 && costUsd > 0 ? costUsd.toFixed(4) : costUsd.toFixed(2)}`
}

function RunTotals({ events }: { events: TraceEvent[] }) {
  const totals = summarizeTrace(events)
  return (
    <dl
      aria-label="Run totals"
      className="text-muted m-0 flex gap-[var(--space-4)] text-xs [font-variant-numeric:tabular-nums]"
    >
      <div className="m-0">
        <dt className="inline">wall </dt>
        <dd className="m-0 inline font-medium">{formatDuration(totals.wallMs)}</dd>
      </div>
      <div className="m-0">
        <dt className="inline">tokens </dt>
        <dd className="m-0 inline font-medium">{formatTokenTotal(totals.tokensTotal)}</dd>
      </div>
      <div className="m-0">
        <dt className="inline">cost </dt>
        <dd className="m-0 inline font-medium">{formatCostTotal(totals.costUsd)}</dd>
      </div>
    </dl>
  )
}

type LoadState =
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | {
      state: 'loaded'
      session: Session
      trace: TraceEvent[]
      traceError: string | null
      messages: Message[]
      messagesError: string | null
    }

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
        const [traceResult, messagesResult] = await Promise.allSettled([
          getTrace(sessionId, controller.signal),
          getMessages(sessionId, controller.signal),
        ])
        if (controller.signal.aborted) return
        if (
          (traceResult.status === 'rejected' && isAbortError(traceResult.reason)) ||
          (messagesResult.status === 'rejected' && isAbortError(messagesResult.reason))
        ) {
          return
        }
        setLoad({
          state: 'loaded',
          session,
          trace: traceResult.status === 'fulfilled' ? traceResult.value : [],
          traceError:
            traceResult.status === 'rejected'
              ? traceResult.reason instanceof Error
                ? traceResult.reason.message
                : 'Unknown trace error'
              : null,
          messages: messagesResult.status === 'fulfilled' ? messagesResult.value : [],
          messagesError:
            messagesResult.status === 'rejected'
              ? messagesResult.reason instanceof Error
                ? messagesResult.reason.message
                : 'Unknown messages error'
              : null,
        })
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
          messages: current.state === 'loaded' ? current.messages : [],
          messagesError: null,
        }))
        return Promise.allSettled([
          getTrace(actionSessionId, controller.signal),
          getMessages(actionSessionId, controller.signal),
        ]).then(([traceResult, messagesResult]) => {
          if (controller.signal.aborted) return
          setLoad((current) => {
            if (current.state !== 'loaded') return current
            const next = { ...current }
            if (traceResult.status === 'fulfilled') {
              next.trace = traceResult.value
              next.traceError = null
            } else if (!isAbortError(traceResult.reason)) {
              next.traceError =
                traceResult.reason instanceof Error
                  ? traceResult.reason.message
                  : 'Unknown trace error'
            }
            if (messagesResult.status === 'fulfilled') {
              next.messages = messagesResult.value
              next.messagesError = null
            } else if (!isAbortError(messagesResult.reason)) {
              next.messagesError =
                messagesResult.reason instanceof Error
                  ? messagesResult.reason.message
                  : 'Unknown messages error'
            }
            return next
          })
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
            <div className="flex flex-wrap items-center gap-[var(--space-4)]">
              <RunTotals events={load.trace} />
              <StatusBadge status={load.session.status} className="px-3 py-[5px] text-xs" />
            </div>
          </div>

          <section aria-label="Chat" className="mb-[var(--space-8)]">
            <ChatPanel
              session={load.session}
              messages={load.messages}
              onSendMessage={(content) =>
                runAction('message', (signal) => sendMessage(sessionId, content, signal))
              }
              submitting={actionKind === 'message'}
              error={messageError}
            />
            {load.messagesError && (
              <div role="alert" className="mt-3 text-sm text-[var(--color-danger)]">
                <p>Could not refresh the conversation: {load.messagesError}</p>
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
