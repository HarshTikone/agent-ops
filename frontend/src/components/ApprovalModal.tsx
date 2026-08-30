import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { PendingAction } from '../lib/api'
import { ShieldIcon } from './icons'

export type ApprovalSubmission = 'approve' | 'reject' | null

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * A blocking security decision. The dialog is portalled outside #app-shell
 * so the rest of the application can be made inert without hiding the modal.
 * Escape deliberately does nothing: only Approve or Reject can resolve it.
 */
export function ApprovalModal({
  pendingAction,
  onApprove,
  onReject,
  submission,
  error,
}: {
  pendingAction: PendingAction
  onApprove: () => void
  onReject: (reason: string) => void
  submission: ApprovalSubmission
  error: string | null
}) {
  const [reasonState, setReasonState] = useState({ actionId: pendingAction.id, value: '' })
  const reason = reasonState.actionId === pendingAction.id ? reasonState.value : ''
  const dialogRef = useRef<HTMLDivElement>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const submitting = submission !== null

  useEffect(() => {
    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const appShell = document.getElementById('app-shell')
    const wasInert = appShell?.inert ?? false
    if (appShell) appShell.inert = true
    headingRef.current?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return

      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      )
      if (focusable.length === 0) {
        event.preventDefault()
        headingRef.current?.focus()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      if (appShell) appShell.inert = wasInert
      previouslyFocused?.focus()
    }
  }, [pendingAction.id])

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[color-mix(in_srgb,var(--color-neutral-900)_50%,transparent)] p-[var(--space-4)]">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-modal-heading"
        aria-describedby="approval-modal-description"
        className="flex w-full max-w-[440px] flex-col gap-[var(--space-3)] rounded-[var(--radius-lg)] bg-[var(--color-surface)] p-[var(--space-4)] shadow-[var(--shadow-lg)]"
      >
        <h2
          ref={headingRef}
          id="approval-modal-heading"
          tabIndex={-1}
          className="flex items-center gap-2 text-[17px] text-[var(--color-warning)] outline-none"
        >
          <ShieldIcon size={18} />
          Approval needed
        </h2>
        <p id="approval-modal-description" className="text-muted m-0 text-sm">
          The agent wants to run an irreversible action before continuing.
        </p>

        <dl className="m-0 rounded-[var(--radius-md)] border border-[var(--color-divider)] p-[var(--space-3)] text-[13px]">
          <div>
            <dt className="text-muted mb-[2px] text-[11px] tracking-[0.08em] uppercase">Tool</dt>
            <dd className="m-0 font-mono">{pendingAction.tool_name}</dd>
          </div>
          <div className="mt-[var(--space-2)]">
            <dt className="text-muted mb-[2px] text-[11px] tracking-[0.08em] uppercase">
              Arguments
            </dt>
            <dd className="m-0">
              <pre className="m-0 overflow-x-auto font-mono text-xs whitespace-pre-wrap">
                {JSON.stringify(pendingAction.tool_args, null, 2)}
              </pre>
            </dd>
          </div>
        </dl>

        <div className="field">
          <label htmlFor="reject-reason">Reason (only used if you reject)</label>
          <textarea
            id="reject-reason"
            value={reason}
            onChange={(event) =>
              setReasonState({ actionId: pendingAction.id, value: event.target.value })
            }
            disabled={submitting}
            maxLength={2_000}
            rows={2}
            className="input resize-y"
            placeholder="Optional"
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-[var(--color-danger)]">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-[var(--space-2)]">
          <button
            type="button"
            onClick={() => onReject(reason)}
            disabled={submitting}
            className="btn btn-secondary border-[var(--color-danger)] text-[var(--color-danger)]"
          >
            {submission === 'reject' ? 'Rejecting…' : 'Reject'}
          </button>
          <button
            type="button"
            onClick={onApprove}
            disabled={submitting}
            className="btn btn-primary"
          >
            {submission === 'approve' ? 'Approving…' : 'Approve'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
