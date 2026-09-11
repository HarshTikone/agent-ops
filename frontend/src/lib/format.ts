/**
 * Shared display formatters for P3 observability values. Kept out of
 * `TraceViewer.tsx` so that component file only exports components (react
 * fast-refresh warns otherwise).
 */

/**
 * `null` means "not measured" (a pre-P3 event, or a node like approval_gate
 * that deliberately doesn't time itself) — rendered as an em dash, never
 * "0ms", so an unmeasured step never reads as an instant one.
 */
export function formatDuration(durationMs: number | null): string {
  if (durationMs === null) return '—'
  if (durationMs < 1000) return `${durationMs}ms`
  return `${(durationMs / 1000).toFixed(1)}s`
}
