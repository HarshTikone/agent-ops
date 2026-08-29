import { fireEvent, render, screen } from '@testing-library/react'
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
        submission={null}
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
        submission={null}
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
        submission={null}
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
        submission={null}
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
        submission="approve"
        error={null}
      />,
    )
    expect(screen.getByRole('button', { name: 'Approving…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    expect(screen.getByLabelText(/reason/i)).toBeDisabled()
  })

  it('shows an error from a failed decision attempt', () => {
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        submission={null}
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
        submission={null}
        error={null}
      />,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
  })

  it('shows a distinct submitting label for rejection', () => {
    render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        submission="reject"
        error={null}
      />,
    )
    expect(screen.getByRole('button', { name: 'Rejecting…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  it('moves focus inside, traps it, makes the app inert, ignores Escape, and restores focus', async () => {
    const user = userEvent.setup()
    const appShell = document.createElement('div')
    appShell.id = 'app-shell'
    const opener = document.createElement('button')
    opener.textContent = 'Open approval'
    appShell.append(opener)
    document.body.append(appShell)
    opener.focus()

    const rendered = render(
      <ApprovalModal
        pendingAction={makePendingAction()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        submission={null}
        error={null}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Approval needed' })).toHaveFocus()
    expect(appShell.inert).toBe(true)

    const approve = screen.getByRole('button', { name: 'Approve' })
    approve.focus()
    await user.tab()
    expect(screen.getByLabelText(/reason/i)).toHaveFocus()
    await user.tab({ shift: true })
    expect(approve).toHaveFocus()

    expect(fireEvent.keyDown(document, { key: 'Escape' })).toBe(false)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    rendered.unmount()
    expect(appShell.inert).toBe(false)
    expect(opener).toHaveFocus()
    appShell.remove()
  })
})
