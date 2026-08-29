import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatPanel } from './ChatPanel'
import type { Session } from '../lib/api'

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: 's1',
    task: '',
    status: 'created',
    final_answer: null,
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
    pending_action: null,
    ...overrides,
  }
}

describe('ChatPanel', () => {
  it('shows a message form when the session has no task yet', () => {
    render(
      <ChatPanel session={makeSession()} onSendMessage={vi.fn()} submitting={false} error={null} />,
    )
    expect(screen.getByLabelText(/what should the agent do/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })

  it('disables Send until the draft has non-whitespace content', async () => {
    const user = userEvent.setup()
    render(
      <ChatPanel session={makeSession()} onSendMessage={vi.fn()} submitting={false} error={null} />,
    )
    const button = screen.getByRole('button', { name: 'Send' })
    expect(button).toBeDisabled()

    await user.type(screen.getByLabelText(/what should the agent do/i), '   ')
    expect(button).toBeDisabled()

    await user.type(screen.getByLabelText(/what should the agent do/i), 'do a thing')
    expect(button).toBeEnabled()
  })

  it('calls onSendMessage with the trimmed draft on submit', async () => {
    const user = userEvent.setup()
    const onSendMessage = vi.fn()
    render(
      <ChatPanel
        session={makeSession()}
        onSendMessage={onSendMessage}
        submitting={false}
        error={null}
      />,
    )

    await user.type(screen.getByLabelText(/what should the agent do/i), '  compute 2+2  ')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(onSendMessage).toHaveBeenCalledWith('compute 2+2')
  })

  it('submits with Enter and keeps Shift+Enter as a newline', async () => {
    const user = userEvent.setup()
    const onSendMessage = vi.fn()
    render(
      <ChatPanel
        session={makeSession()}
        onSendMessage={onSendMessage}
        submitting={false}
        error={null}
      />,
    )
    const input = screen.getByLabelText(/what should the agent do/i)
    await user.type(input, 'line one{Shift>}{Enter}{/Shift}line two')
    expect(onSendMessage).not.toHaveBeenCalled()
    expect(input).toHaveValue('line one\nline two')

    await user.type(input, '{Enter}')
    expect(onSendMessage).toHaveBeenCalledWith('line one\nline two')
  })

  it('matches the server-side 8,000 character limit', () => {
    render(
      <ChatPanel session={makeSession()} onSendMessage={vi.fn()} submitting={false} error={null} />,
    )
    expect(screen.getByLabelText(/what should the agent do/i)).toHaveAttribute('maxlength', '8000')
  })

  it('shows a submitting state and disables the form while a message is in flight', () => {
    render(
      <ChatPanel session={makeSession()} onSendMessage={vi.fn()} submitting={true} error={null} />,
    )
    expect(screen.getByRole('button', { name: 'Thinking…' })).toBeDisabled()
    expect(screen.getByLabelText(/what should the agent do/i)).toBeDisabled()
  })

  it('shows the task and final answer once the session has run', () => {
    render(
      <ChatPanel
        session={makeSession({ status: 'done', task: 'what is 2+2?', final_answer: 'It is 4.' })}
        onSendMessage={vi.fn()}
        submitting={false}
        error={null}
      />,
    )
    expect(screen.getByText('what is 2+2?')).toBeInTheDocument()
    expect(screen.getByText('It is 4.')).toBeInTheDocument()
    expect(screen.queryByLabelText(/what should the agent do/i)).not.toBeInTheDocument()
  })

  it('shows a thinking indicator when running with no answer yet', () => {
    render(
      <ChatPanel
        session={makeSession({ status: 'running', task: 'do something' })}
        onSendMessage={vi.fn()}
        submitting={false}
        error={null}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Thinking…')
  })

  it('shows a paused indicator when awaiting approval', () => {
    render(
      <ChatPanel
        session={makeSession({ status: 'awaiting_approval', task: 'save a note' })}
        onSendMessage={vi.fn()}
        submitting={false}
        error={null}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Paused')
  })

  it('surfaces an error passed in from the parent', () => {
    render(
      <ChatPanel
        session={makeSession()}
        onSendMessage={vi.fn()}
        submitting={false}
        error="network blip"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('network blip')
  })

  it('does not hide a message error when the session is awaiting approval', () => {
    render(
      <ChatPanel
        session={makeSession({ status: 'awaiting_approval', task: 'save a note' })}
        onSendMessage={vi.fn()}
        submitting={false}
        error="message response was interrupted"
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('message response was interrupted')
  })
})
