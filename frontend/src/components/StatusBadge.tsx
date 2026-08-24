import type { SessionStatus } from '../lib/api'

// Record-typed, not a switch/if-chain: adding a status to the union
// without adding it here is a compile error, not a silent fallback color
// (same exhaustiveness pattern as BackendStatus's statusColor).
const LABELS: Record<SessionStatus, string> = {
  created: 'New',
  running: 'Running',
  awaiting_approval: 'Needs approval',
  done: 'Done',
  failed: 'Failed',
}

const COLORS: Record<SessionStatus, string> = {
  created: 'bg-neutral-800 text-neutral-300',
  running: 'bg-blue-950 text-blue-300',
  awaiting_approval: 'bg-amber-950 text-amber-300',
  done: 'bg-green-950 text-green-300',
  failed: 'bg-red-950 text-red-300',
}

export function StatusBadge({ status }: { status: SessionStatus }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium whitespace-nowrap ${COLORS[status]}`}
    >
      {LABELS[status]}
    </span>
  )
}
