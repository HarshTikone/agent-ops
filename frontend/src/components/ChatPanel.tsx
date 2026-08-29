import { useState, type FormEvent, type KeyboardEvent } from 'react'
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
  const maxMessageLength = 8_000

  if (session.status === 'created') {
    const handleSubmit = (e: FormEvent) => {
      e.preventDefault()
      const content = draft.trim()
      if (content && content.length <= maxMessageLength) onSendMessage(content)
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        event.currentTarget.form?.requestSubmit()
      }
    }

    return (
      <form onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="task-input">What should the agent do?</label>
          <textarea
            id="task-input"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={submitting}
            maxLength={maxMessageLength}
            aria-describedby="task-input-limit"
            rows={3}
            className="input resize-y"
            placeholder="e.g. What is 47 times 89? Use the calculator tool."
          />
        </div>

        <div className="mt-[var(--space-2)] flex items-center justify-between gap-[var(--space-3)]">
          <span id="task-input-limit" className="text-muted text-xs">
            {draft.length.toLocaleString()} / {maxMessageLength.toLocaleString()} characters
          </span>
          <button
            type="submit"
            disabled={submitting || draft.trim() === '' || draft.trim().length > maxMessageLength}
            className="btn btn-primary"
          >
            {submitting ? 'Thinking…' : 'Send'}
          </button>
        </div>

        {error && (
          <p role="alert" className="mt-[var(--space-2)] text-sm text-[var(--color-danger)]">
            {error}
          </p>
        )}
      </form>
    )
  }

  return (
    <div className="flex flex-col gap-[var(--space-3)]">
      <div className="max-w-[80%] self-end rounded-[var(--radius-md)] bg-[var(--color-accent-100)] p-[var(--space-3)] text-sm text-[var(--color-accent-800)]">
        {session.task}
      </div>

      {session.final_answer && (
        <div className="max-w-[80%] self-start rounded-[var(--radius-md)] border border-[var(--color-divider)] bg-[var(--color-surface)] p-[var(--space-3)] text-sm">
          {session.final_answer}
        </div>
      )}

      {!session.final_answer && session.status === 'running' && (
        <p role="status" className="text-muted text-[13px]">
          <span className="pulse-dot mr-[6px]" />
          Thinking…
        </p>
      )}

      {!session.final_answer && session.status === 'awaiting_approval' && (
        <p role="status" className="text-[13px] text-[var(--color-warning)]">
          Paused — waiting for your approval below.
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          {error}
        </p>
      )}
    </div>
  )
}
