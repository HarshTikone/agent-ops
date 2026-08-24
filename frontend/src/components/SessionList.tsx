import { Link } from 'react-router-dom'
import type { Session } from '../lib/api'
import { StatusBadge } from './StatusBadge'

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString()
}

export function SessionList({ sessions }: { sessions: Session[] }) {
  if (sessions.length === 0) {
    return <p className="text-sm text-neutral-500">No sessions yet — start one above.</p>
  }

  return (
    <ul className="flex flex-col gap-2">
      {sessions.map((session) => (
        <li key={session.id}>
          <Link
            to={`/sessions/${session.id}`}
            className="flex items-center justify-between gap-3 rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm hover:border-neutral-600"
          >
            <span className="truncate text-neutral-200">
              {session.task || <span className="text-neutral-500 italic">Untitled session</span>}
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="text-xs text-neutral-500">
                {formatTimestamp(session.created_at)}
              </span>
              <StatusBadge status={session.status} />
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}
