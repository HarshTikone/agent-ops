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
  onArchive,
  onRestore,
}: {
  sessions: Session[]
  onArchive?: (sessionId: string) => void
  onRestore?: (sessionId: string) => void
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
              clicking anywhere opens the session, while the archive/restore
              button stays a sibling above it rather than a nested
              interactive element inside an anchor. */}
          <Link
            to={`/sessions/${session.id}`}
            className="flex flex-1 flex-col gap-[var(--space-3)] after:absolute after:inset-0 after:content-['']"
          >
            <span className="card-kicker pr-[28px]">SESSION · {shortId(session.id)}</span>
            <h2 className="card-title flex-1">
              {/* `title` is stable across follow-up turns (WP5, ADR-036);
                  `task` is what a brand-new session shows before it has one. */}
              {session.title || session.task || (
                <span className="text-muted italic">Untitled session</span>
              )}
            </h2>
            <span className="card-meta">
              <StatusBadge status={session.status} />
              {session.archived_at && (
                <>
                  <span aria-hidden="true">·</span>
                  <span className="tag tag-neutral">Archived</span>
                </>
              )}
              <span aria-hidden="true">·</span>
              <span>{formatRelativeTime(session.created_at)}</span>
            </span>
          </Link>

          {/* Belt and braces: the link is a sibling, not an ancestor, but
              this control must never trigger the card's open action. */}
          {session.archived_at && onRestore && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onRestore(session.id)
              }}
              className="btn btn-ghost absolute top-[var(--space-2)] right-[var(--space-2)] z-10 px-2 py-1 text-xs"
            >
              Restore
            </button>
          )}

          {!session.archived_at && onArchive && (
            <button
              type="button"
              aria-label={`Archive session ${shortId(session.id)}`}
              title="Archive this session"
              onClick={(event) => {
                event.stopPropagation()
                onArchive(session.id)
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
