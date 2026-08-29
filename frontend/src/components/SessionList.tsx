import { Link } from 'react-router-dom'
import type { Session } from '../lib/api'
import { StatusBadge } from './StatusBadge'
import { TrashIcon } from './icons'

/** "just now" / "12m ago" / "3h ago", then a plain date beyond a day. */
function formatRelativeTime(iso: string): string {
  const created = new Date(iso)
  const diffMinutes = Math.round((Date.now() - created.getTime()) / 60_000)
  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return created.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function shortId(id: string): string {
  return id.slice(-4).toUpperCase()
}

const CORNERS = ['corner-tl', 'corner-tr', 'corner-bl', 'corner-br']

export function SessionList({
  sessions,
  onRemove,
}: {
  sessions: Session[]
  onRemove?: (sessionId: string) => void
}) {
  if (sessions.length === 0) {
    return <p className="text-muted text-sm">No sessions yet — start one above.</p>
  }

  return (
    <ul className="grid list-none grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-[var(--space-6)] p-0">
      {sessions.map((session) => (
        <li
          key={session.id}
          className="blueprint relative flex min-h-[158px] flex-col p-[var(--space-4)] transition-colors hover:border-[var(--color-accent)]"
        >
          {CORNERS.map((corner) => (
            <span key={corner} aria-hidden="true" className={`corner ${corner}`} />
          ))}

          {/* The link is stretched over the whole card (::after inset-0) so
              clicking anywhere opens the session, while the remove button
              stays a sibling above it rather than a nested interactive
              element inside an anchor. */}
          <Link
            to={`/sessions/${session.id}`}
            className="flex flex-1 flex-col gap-[var(--space-3)] after:absolute after:inset-0 after:content-['']"
          >
            <span className="card-kicker pr-[28px]">SESSION · {shortId(session.id)}</span>
            <h3 className="card-title flex-1">
              {session.task || <span className="text-muted italic">Untitled session</span>}
            </h3>
            <span className="card-meta">
              <StatusBadge status={session.status} />
              <span aria-hidden="true">·</span>
              <span>{formatRelativeTime(session.created_at)}</span>
            </span>
          </Link>

          {onRemove && (
            <button
              type="button"
              aria-label={`Remove session ${shortId(session.id)}`}
              title="Hide this session on this device"
              onClick={(event) => {
                // Belt and braces: the link is a sibling, not an ancestor,
                // but this control must never trigger the card's open action.
                event.stopPropagation()
                onRemove(session.id)
              }}
              className="btn btn-ghost btn-icon-sm absolute top-[var(--space-2)] right-[var(--space-2)] z-10"
            >
              <TrashIcon size={14} />
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
