import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircleIcon, ShieldIcon, TriangleAlertIcon } from '../components/icons'
import { TraceViewer } from '../components/TraceViewer'
import type { TraceEvent } from '../lib/api'

const SESSION_ID = 'recruiter-demo'
const STARTED_AT = '2026-09-18T14:30:00.000Z'

function event(
  id: number,
  node: string,
  detail: string,
  level: TraceEvent['level'],
  provider: string | null = null,
  durationMs: number | null = null,
): TraceEvent {
  return {
    id,
    session_id: SESSION_ID,
    sequence: id,
    node,
    detail,
    level,
    provider,
    created_at: new Date(Date.parse(STARTED_AT) + id * 900).toISOString(),
    started_at: durationMs === null ? null : STARTED_AT,
    duration_ms: durationMs,
    tokens_in: provider ? 312 : null,
    tokens_out: provider ? 96 : null,
    cost_usd: provider ? '0.000084' : null,
  }
}

const BEFORE_APPROVAL: TraceEvent[] = [
  event(
    1,
    'planner',
    'plan: research official reliability guidance -> compare sources -> draft incident note -> request approval before publishing',
    'info',
    'gemini',
    624,
  ),
  event(
    2,
    'provider_failover',
    'Gemini returned 503; circuit opened and the same structured request moved to OpenRouter',
    'warning',
    'openrouter',
    1180,
  ),
  event(
    3,
    'delegate',
    'step=0 tool=web_search query="official guidance for resilient AI agent operations"',
    'info',
  ),
  event(
    4,
    'tool_call',
    'FAILED (transient): upstream search timed out after 2.0s',
    'warning',
    null,
    2000,
  ),
  event(
    5,
    'recovery',
    'retry 1/2 with bounded backoff and a narrower official-domain query',
    'warning',
  ),
  event(6, 'tool_call', 'OK: 3 official sources retrieved and normalized', 'success', null, 438),
  event(
    7,
    'security',
    'PROMPT INJECTION BLOCKED: retrieved page attempted to override system instructions; untrusted directives were removed while factual content was retained',
    'error',
  ),
  event(
    8,
    'verify',
    '3 claims cross-checked against 2 independent official sources; citations attached',
    'success',
    'openrouter',
    512,
  ),
  event(
    9,
    'approval_gate',
    'PAUSED: publishing "vendor-reliability-brief" changes shared workspace state and requires human approval',
    'warning',
  ),
]

const AFTER_APPROVAL: TraceEvent[] = [
  event(10, 'approval_gate', 'APPROVED by human operator; execution may resume', 'success'),
  event(
    11,
    'tool_call',
    'OK: notes_store wrote vendor-reliability-brief with 3 citations and an audit checksum',
    'success',
    null,
    84,
  ),
  event(12, 'verify', 'write confirmed; stored content matches the approved draft', 'success'),
  event(
    13,
    'finalize',
    'completed with provider failover, one recovered tool error, one blocked injection, and one approved write',
    'success',
    'openrouter',
    321,
  ),
]

const CAPABILITIES = [
  ['Multi-step research', '3 cited claims'],
  ['Provider failover', 'Gemini → OpenRouter'],
  ['Tool recovery', 'Timeout → bounded retry'],
  ['Injection defense', 'Untrusted instruction blocked'],
  ['Human approval', 'Write paused before execution'],
]

function CornerMarks() {
  return (
    <>
      <span className="corner corner-tl" />
      <span className="corner corner-tr" />
      <span className="corner corner-bl" />
      <span className="corner corner-br" />
    </>
  )
}

export function RecruiterDemoPage() {
  const [approved, setApproved] = useState(false)
  const events = approved ? [...BEFORE_APPROVAL, ...AFTER_APPROVAL] : BEFORE_APPROVAL

  return (
    <main className="mx-auto flex w-full max-w-[1120px] flex-col px-[var(--space-6)] py-[var(--space-8)]">
      <div className="flex flex-wrap items-start justify-between gap-[var(--space-6)]">
        <div className="max-w-[760px]">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="tag tag-accent">GUIDED RESILIENCE DEMO</span>
            <span className="text-muted text-xs">Deterministic · No credentials required</span>
          </div>
          <h1 className="text-[34px]">Research safely. Recover visibly. Act only with approval.</h1>
          <p className="text-muted mt-2 max-w-[720px] text-sm">
            One auditable run researches official reliability guidance, survives a provider outage,
            recovers from a failed tool call, blocks prompt injection, and pauses before changing
            shared state.
          </p>
        </div>
        <Link to="/" className="btn btn-secondary">
          All sessions
        </Link>
      </div>

      <section
        aria-label="Demo capabilities"
        className="mt-[var(--space-8)] grid gap-3 md:grid-cols-5"
      >
        {CAPABILITIES.map(([name, result]) => (
          <article key={name} className="blueprint p-[var(--space-4)]">
            <CornerMarks />
            <p className="card-kicker">Verified behavior</p>
            <h2 className="card-title mt-1">{name}</h2>
            <p className="text-muted mt-2 text-xs">{result}</p>
          </article>
        ))}
      </section>

      <div className="mt-[var(--space-8)] grid items-start gap-[var(--space-6)] lg:grid-cols-[0.82fr_1.18fr]">
        <section aria-labelledby="mission-heading" className="blueprint p-[var(--space-6)]">
          <CornerMarks />
          <p className="card-kicker">Mission · REC-042</p>
          <h2 id="mission-heading" className="mt-1 text-[22px]">
            Prepare a cited vendor reliability brief
          </h2>
          <p className="text-muted mt-2 text-sm">
            Research official sources, reject untrusted instructions, and save the verified brief to
            the shared notes workspace.
          </p>

          <dl className="mt-[var(--space-6)] grid grid-cols-3 gap-3 border-y border-[var(--color-divider)] py-[var(--space-4)] text-xs">
            <div>
              <dt className="text-muted">Provider</dt>
              <dd className="mt-1 font-semibold">OpenRouter fallback</dd>
            </div>
            <div>
              <dt className="text-muted">Sources</dt>
              <dd className="mt-1 font-semibold">3 official</dd>
            </div>
            <div>
              <dt className="text-muted">Risk</dt>
              <dd className="mt-1 font-semibold">Shared-state write</dd>
            </div>
          </dl>

          {!approved ? (
            <div className="mt-[var(--space-6)] border border-[var(--color-warning)] bg-[color-mix(in_srgb,var(--color-warning)_9%,transparent)] p-[var(--space-4)]">
              <div className="flex items-center gap-2 text-[var(--color-warning)]">
                <ShieldIcon />
                <h3 className="text-base">Human approval required</h3>
              </div>
              <p className="mt-2 text-sm">
                <strong>notes_store.write</strong> will publish the verified brief as
                <code className="ml-1">vendor-reliability-brief</code>.
              </p>
              <p className="text-muted mt-2 text-xs">
                The write has not executed. This guided state mirrors the production durable
                approval gate.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" className="btn btn-primary" onClick={() => setApproved(true)}>
                  Approve and resume
                </button>
                <button type="button" className="btn btn-secondary" disabled>
                  Reject
                </button>
              </div>
            </div>
          ) : (
            <div
              role="status"
              className="mt-[var(--space-6)] border border-[var(--color-success)] bg-[color-mix(in_srgb,var(--color-success)_9%,transparent)] p-[var(--space-4)]"
            >
              <div className="flex items-center gap-2 text-[var(--color-success)]">
                <CheckCircleIcon />
                <h3 className="text-base">Run completed safely</h3>
              </div>
              <p className="mt-2 text-sm">
                The approved brief was written with three citations and an audit checksum.
              </p>
              <button
                type="button"
                className="btn btn-secondary mt-4"
                onClick={() => setApproved(false)}
              >
                Replay approval step
              </button>
            </div>
          )}

          <div className="mt-[var(--space-6)] flex items-start gap-2 text-xs text-[var(--color-warning)]">
            <TriangleAlertIcon className="mt-[1px] flex-none" />
            <p>
              Prompt injection was isolated from source content before verification; it never
              entered the planner context.
            </p>
          </div>
        </section>

        <section aria-labelledby="trace-heading" className="blueprint p-[var(--space-6)]">
          <CornerMarks />
          <div className="mb-[var(--space-6)] flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="card-kicker">Durable execution record</p>
              <h2 id="trace-heading" className="mt-1 text-[22px]">
                Agent trace
              </h2>
            </div>
            <span className={approved ? 'tag tag-success' : 'tag tag-warning'}>
              {approved ? 'COMPLETED' : 'AWAITING APPROVAL'}
            </span>
          </div>
          <TraceViewer events={events} />
        </section>
      </div>
    </main>
  )
}
