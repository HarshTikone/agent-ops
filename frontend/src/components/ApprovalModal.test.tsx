import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApprovalModal } from './ApprovalModal'
import type { PendingAction } from '../lib/api'

function makePendingAction(overrides: Partial<PendingAction> = {}): PendingAction {
  return {
    id: 'p1',
    session_id: 's1',
    tool_name: 'notes_store',
    tool_args: { action: 'write', key: 'topic', content: 'agent ops' },
    status: 'pending',
    reason: null,
    created_at: '2026-08-24T00:00:00Z',
    decided_at: null,
    ...overrides,
  }
}

describe('ApprovalModal', () => {
  it('shows the tool name and args', () => {
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        submitting={false}
        error={null}
      />,
    )
    expect(screen.getByText('notes_store')).toBeInTheDocument()
    expect(screen.getByText(/"key": "topic"/)).toBeInTheDocument()
    expect(screen.getByText(/"content": "agent ops"/)).toBeInTheDocument()
  })

  it('calls onApprove when Approve is clicked', async () => {
    const user = userEvent.setup()
    const onApprove = vi.fn()
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={onApprove}
        onReject={vi.fn()}
        submitting={false}
        error={null}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(onApprove).toHaveBeenCalledOnce()
  })

  it('calls onReject with the typed reason', async () => {
    const user = userEvent.setup()
    const onReject = vi.fn()
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={onReject}
        submitting={false}
        error={null}
      />,
    )
    await user.type(screen.getByLabelText(/reason/i), 'not needed')
    await user.click(screen.getByRole('button', { name: 'Reject' }))
    expect(onReject).toHaveBeenCalledWith('not needed')
  })

  it('calls onReject with an empty reason when none was typed', async () => {
    const user = userEvent.setup()
    const onReject = vi.fn()
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={onReject}
        submitting={false}
        error={null}
      />,
    )
    await user.click(screen.getByRole('button', { name: 'Reject' }))
    expect(onReject).toHaveBeenCalledWith('')
  })

  it('disables both buttons and the reason field while submitting', () => {
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        submitting={true}
        error={null}
      />,
    )
    expect(screen.getByRole('button', { name: 'Working…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    expect(screen.getByLabelText(/reason/i)).toBeDisabled()
  })

  it('shows an error from a failed decision attempt', () => {
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        submitting={false}
        error="pending action already approved, not 'pending'"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('already approved')
  })

  it('renders as an accessible modal dialog', () => {
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        submitting={false}
        error={null}
      />,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
  })
})
