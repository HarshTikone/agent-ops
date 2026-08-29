import type { ReactNode } from 'react'
import type { TraceEvent } from '../lib/api'
import { CheckCircleIcon, InfoCircleIcon, TriangleAlertIcon, XCircleIcon } from './icons'

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
  if (event.level !== 'info') return event.level

  // Compatibility fallback for rows created before structured levels were
  // introduced. New events always use the explicit field above.
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

// One token per tone, used for the rail, the icon and the node label alike.
const TONE_COLORS: Record<Tone, string> = {
  default: 'var(--color-neutral-500)',
  success: 'var(--color-success)',
  warning: 'var(--color-warning)',
  error: 'var(--color-danger)',
}

const TONE_ICONS: Record<Tone, ReactNode> = {
  default: <InfoCircleIcon size={14} />,
  success: <CheckCircleIcon size={14} />,
  warning: <TriangleAlertIcon size={14} />,
  error: <XCircleIcon size={14} />,
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
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function TraceViewer({ events }: { events: TraceEvent[] }) {
  if (events.length === 0) {
    return <p className="text-muted text-[13px]">No trace events yet.</p>
  }

  return (
    <ol aria-label="Agent trace" className="flex list-none flex-col gap-[var(--space-4)] p-0">
      {events.map((event) => {
        const tone = toneFor(event)
        const color = TONE_COLORS[tone]
        return (
          <li
            key={event.id}
            data-tone={tone}
            className="flex gap-[var(--space-2)] border-l-2 py-[2px] pl-[var(--space-3)]"
            style={{ borderColor: color }}
          >
            <span className="mt-[1px] flex-none" style={{ color }}>
              {TONE_ICONS[tone]}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span
                  className="[font-family:var(--font-heading)] text-xs font-semibold tracking-[0.04em]"
                  style={{ color }}
                >
                  {nodeLabel(event.node)}
                </span>
                {event.provider && (
                  <span className="text-muted text-[11px]">via {event.provider}</span>
                )}
                <span className="text-muted text-[11px]">{formatTime(event.created_at)}</span>
              </div>
              <p className="mt-[3px] text-[13px] break-words">{event.detail}</p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
