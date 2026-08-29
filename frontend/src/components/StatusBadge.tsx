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

// Tag fills come from the Industry token sheet (see index.css) so the same
// class carries the right tint in both themes.
const TAG_CLASSES: Record<SessionStatus, string> = {
  created: 'tag-neutral',
  running: 'tag-accent',
  awaiting_approval: 'tag-warning',
  done: 'tag-success',
  failed: 'tag-danger',
}

export function StatusBadge({ status, className }: { status: SessionStatus; className?: string }) {
  return (
    <span className={`tag ${TAG_CLASSES[status]}${className ? ` ${className}` : ''}`}>
      {LABELS[status]}
    </span>
  )
}
