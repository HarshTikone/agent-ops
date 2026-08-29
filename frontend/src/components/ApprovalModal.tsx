import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { PendingAction } from '../lib/api'

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
  const [reason, setReason] = useState('')
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
  }, [])

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-modal-heading"
        aria-describedby="approval-modal-description"
        className="w-full max-w-md rounded-lg border border-amber-800 bg-neutral-900 p-5"
      >
        <h2
          ref={headingRef}
          id="approval-modal-heading"
          tabIndex={-1}
          className="text-lg font-semibold text-amber-300 outline-none"
        >
          Approval needed
        </h2>
        <p id="approval-modal-description" className="mt-1 text-sm text-neutral-400">
          The agent wants to run an irreversible action before continuing.
        </p>

        <dl className="mt-4 space-y-2 rounded border border-neutral-800 bg-neutral-950 p-3 text-sm">
          <div>
            <dt className="text-xs tracking-wide text-neutral-500 uppercase">Tool</dt>
            <dd className="font-mono text-neutral-200">{pendingAction.tool_name}</dd>
          </div>
          <div>
            <dt className="text-xs tracking-wide text-neutral-500 uppercase">Arguments</dt>
            <dd>
              <pre className="mt-1 overflow-x-auto font-mono text-xs text-neutral-300">
                {JSON.stringify(pendingAction.tool_args, null, 2)}
              </pre>
            </dd>
          </div>
        </dl>

        <label htmlFor="reject-reason" className="mt-4 block text-sm text-neutral-400">
          Reason (only used if you reject)
        </label>
        <textarea
          id="reject-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          disabled={submitting}
          maxLength={2_000}
          rows={2}
          className="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 p-2 text-sm text-neutral-200 disabled:opacity-50"
          placeholder="Optional"
        />

        {error && (
          <p role="alert" className="mt-2 text-sm text-red-400">
            {error}
          </p>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onReject(reason)}
            disabled={submitting}
            className="rounded border border-red-800 px-3 py-1.5 text-sm text-red-300 hover:bg-red-950 disabled:opacity-50"
          >
            {submission === 'reject' ? 'Rejecting…' : 'Reject'}
          </button>
          <button
            type="button"
            onClick={onApprove}
            disabled={submitting}
            className="rounded bg-green-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-600 disabled:opacity-50"
          >
            {submission === 'approve' ? 'Approving…' : 'Approve'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
