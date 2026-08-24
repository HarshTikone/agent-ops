import { useState } from 'react'
import type { PendingAction } from '../lib/api'

/**
 * The UI's view onto pending_actions (ARCHITECTURE.md §2): this modal is
 * NOT the source of truth for the approval state — it just renders whatever
 * `pending_action` the session response embeds (ADR-018) and calls back
 * into the parent, which owns the actual approve/reject requests. A page
 * reload mid-approval loses nothing: refetching the session shows the same
 * pending_action again.
 */
export function ApprovalModal({
  pendingAction,
  onApprove,
  onReject,
  submitting,
  error,
}: {
  pendingAction: PendingAction
  onApprove: () => void
  onReject: (reason: string) => void
  submitting: boolean
  error: string | null
}) {
  const [reason, setReason] = useState('')

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="approval-modal-heading"
      className="fixed inset-0 flex items-center justify-center bg-black/60 p-4"
    >
      <div className="w-full max-w-md rounded-lg border border-amber-800 bg-neutral-900 p-5">
        <h2 id="approval-modal-heading" className="text-lg font-semibold text-amber-300">
          Approval needed
        </h2>
        <p className="mt-1 text-sm text-neutral-400">
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
          onChange={(e) => setReason(e.target.value)}
          disabled={submitting}
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
            Reject
          </button>
          <button
            type="button"
            onClick={onApprove}
            disabled={submitting}
            className="rounded bg-green-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-600 disabled:opacity-50"
          >
            {submitting ? 'Working…' : 'Approve'}
          </button>
        </div>
      </div>
    </div>
  )
}
