import { useState, type FormEvent } from 'react'
import type { Session } from '../lib/api'

/**
 * Day 3's graph design is one task per session (ADR-015) — a session with
 * status 'created' shows the message form (its first message becomes the
 * task and starts the one graph run); every other status shows the
 * task/answer transcript instead, since a second message would be a 409.
 */
export function ChatPanel({
  session,
  onSendMessage,
  submitting,
  error,
}: {
  session: Session
  onSendMessage: (content: string) => void
  submitting: boolean
  error: string | null
}) {
  const [draft, setDraft] = useState('')

  if (session.status === 'created') {
    const handleSubmit = (e: FormEvent) => {
      e.preventDefault()
      const content = draft.trim()
      if (content) onSendMessage(content)
    }

    return (
      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <label htmlFor="task-input" className="text-sm text-neutral-400">
          What should the agent do?
        </label>
        <textarea
          id="task-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={submitting}
          rows={3}
          className="rounded border border-neutral-700 bg-neutral-950 p-2 text-sm text-neutral-100 disabled:opacity-50"
          placeholder="e.g. What is 47 times 89? Use the calculator tool."
        />
        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting || draft.trim() === ''}
          className="self-start rounded bg-blue-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
        >
          {submitting ? 'Thinking…' : 'Send'}
        </button>
      </form>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="self-end rounded-lg bg-blue-900 px-3 py-2 text-sm text-blue-100">
        {session.task}
      </div>

      {session.final_answer && (
        <div className="self-start rounded-lg bg-neutral-800 px-3 py-2 text-sm text-neutral-100">
          {session.final_answer}
        </div>
      )}

      {!session.final_answer && session.status === 'running' && (
        <p role="status" className="text-sm text-neutral-500">
          Thinking…
        </p>
      )}

      {!session.final_answer && session.status === 'awaiting_approval' && (
        <p role="status" className="text-sm text-amber-400">
          Paused — waiting for your approval below.
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      )}
    </div>
  )
}
