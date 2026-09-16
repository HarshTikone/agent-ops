import { useState, type FormEvent, type KeyboardEvent } from 'react'
import type { Session, SessionStatus } from '../lib/api'

const MAX_MESSAGE_LENGTH = 8_000

// A session reaching one of these can still take a follow-up message
// (ADR-030 supersedes ADR-015's one-task-per-session boundary): the prior
// turn's messages and trace carry forward, so the agent can build on what
// it already did and said. 'running' and 'awaiting_approval' are genuinely
// mid-flight -- a message there would 409, so no compose box for those.
const RESTARTABLE_STATUSES: SessionStatus[] = ['done', 'degraded', 'failed']

function MessageComposer({
  onSendMessage,
  submitting,
  error,
  label,
  placeholder,
  submitLabel,
}: {
  onSendMessage: (content: string) => void
  submitting: boolean
  error: string | null
  label: string
  placeholder: string
  submitLabel: string
}) {
  const [draft, setDraft] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const content = draft.trim()
    if (content && content.length <= MAX_MESSAGE_LENGTH) {
      onSendMessage(content)
      setDraft('')
    }
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
        <label htmlFor="task-input">{label}</label>
        <textarea
          id="task-input"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={submitting}
          maxLength={MAX_MESSAGE_LENGTH}
          aria-describedby="task-input-limit"
          rows={3}
          className="input resize-y"
          placeholder={placeholder}
        />
      </div>

      <div className="mt-[var(--space-2)] flex items-center justify-between gap-[var(--space-3)]">
        <span id="task-input-limit" className="text-muted text-xs">
          {draft.length.toLocaleString()} / {MAX_MESSAGE_LENGTH.toLocaleString()} characters
        </span>
        <button
          type="submit"
          disabled={submitting || draft.trim() === '' || draft.trim().length > MAX_MESSAGE_LENGTH}
          className="btn btn-primary"
        >
          {submitting ? 'Thinking…' : submitLabel}
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

/**
 * A session with status 'created' shows only the message form (its first
 * message becomes the task and starts the one graph run). Every other
 * status shows the task/answer transcript; a terminal one (done/degraded/
 * failed) additionally shows a follow-up composer below it, since those can
 * still take a new message (ADR-030).
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
  if (session.status === 'created') {
    return (
      <MessageComposer
        onSendMessage={onSendMessage}
        submitting={submitting}
        error={error}
        label="What should the agent do?"
        placeholder="e.g. What is 47 times 89? Use the calculator tool."
        submitLabel="Send"
      />
    )
  }

  const canContinue = RESTARTABLE_STATUSES.includes(session.status)

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

      {error && !canContinue && (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          {error}
        </p>
      )}

      {canContinue && (
        <div className="mt-[var(--space-2)] border-t border-[var(--color-divider)] pt-[var(--space-4)]">
          <MessageComposer
            onSendMessage={onSendMessage}
            submitting={submitting}
            error={error}
            label="Send a follow-up"
            placeholder="Ask the agent to continue, or start something new in this session…"
            submitLabel="Send"
          />
        </div>
      )}
    </div>
  )
}
