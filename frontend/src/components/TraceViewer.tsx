import type { TraceEvent } from '../lib/api'

/**
 * The trace IS the product, not a debugging afterthought (ARCHITECTURE.md
 * §0) — this renders every agent decision and tool call as it happened, not
 * just the final answer. Node names are shown as-is (they're the graph's
 * real node identifiers: planner/delegate/approval_gate/tool_call/observe/
 * decide_next/finalize — ARCHITECTURE.md §2), colored by what actually
 * happened rather than by node type alone, so a retry or a rejection is
 * visible at a glance without reading every line of detail text.
 */

type Tone = 'default' | 'success' | 'warning' | 'error'

function toneFor(event: TraceEvent): Tone {
  const detail = event.detail
  if (
    detail.includes('FAILED (permanent)') ||
    detail.includes('REJECTED') ||
    detail.includes('give_up')
  ) {
    return 'error'
  }
  if (
    detail.includes('FAILED (transient)') ||
    detail.includes('retry') ||
    detail.includes('replan')
  ) {
    return 'warning'
  }
  if (detail.includes('APPROVED') || detail.startsWith('OK:') || detail.includes('-> finalize')) {
    return 'success'
  }
  return 'default'
}

const TONE_STYLES: Record<Tone, string> = {
  default: 'border-neutral-700 text-neutral-300',
  success: 'border-green-800 text-green-300',
  warning: 'border-amber-800 text-amber-300',
  error: 'border-red-800 text-red-300',
}

const NODE_LABELS: Record<string, string> = {
  planner: 'PLANNER',
  delegate: 'DELEGATE',
  approval_gate: 'APPROVAL',
  tool_call: 'TOOL CALL',
  observe: 'OBSERVE',
  decide_next: 'DECIDE',
  finalize: 'FINALIZE',
}

function nodeLabel(node: string): string {
  return NODE_LABELS[node] ?? node.toUpperCase()
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString()
}

export function TraceViewer({ events }: { events: TraceEvent[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-neutral-500">No trace events yet.</p>
  }

  return (
    <ol aria-label="Agent trace" className="flex flex-col gap-2">
      {events.map((event) => {
        const tone = toneFor(event)
        return (
          <li
            key={event.id}
            className={`border-l-2 py-1 pl-3 text-sm ${TONE_STYLES[tone]}`}
            data-tone={tone}
          >
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-xs font-semibold tracking-wide">
                {nodeLabel(event.node)}
              </span>
              {event.provider && (
                <span className="text-xs text-neutral-500">via {event.provider}</span>
              )}
              <span className="text-xs text-neutral-600">{formatTime(event.created_at)}</span>
            </div>
            <p className="mt-0.5 break-words text-neutral-200">{event.detail}</p>
          </li>
        )
      })}
    </ol>
  )
}
