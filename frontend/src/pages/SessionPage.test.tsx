import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionPage } from './SessionPage'
import * as api from '../lib/api'
import type { Session, TraceEvent } from '../lib/api'

const SESSION_ID = '91255bea-f210-48b0-a3df-8dea7938d645'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof api>('../lib/api')
  return {
    ...actual,
    getSession: vi.fn(),
    getTrace: vi.fn(),
    sendMessage: vi.fn(),
    approvePendingAction: vi.fn(),
    rejectPendingAction: vi.fn(),
  }
})

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: SESSION_ID,
    task: '',
    status: 'created',
    final_answer: null,
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
    pending_action: null,
    ...overrides,
  }
}

function renderPage(entry = `/sessions/${SESSION_ID}`) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/sessions/:sessionId" element={<SessionPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SessionPage', () => {
  beforeEach(() => {
    vi.mocked(api.getSession).mockReturnValue(new Promise(() => {}))
    vi.mocked(api.getTrace).mockReturnValue(new Promise(() => {}))
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows a loading state before the session and trace resolve', () => {
    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent('Loading session')
  })

  it('shows an error state when the session fails to load', async () => {
    vi.mocked(api.getSession).mockRejectedValue(new Error('session not found'))
    vi.mocked(api.getTrace).mockResolvedValue([])
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('session not found')
  })

  it('renders the chat panel and trace once loaded', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      makeSession({ status: 'done', task: 'do a thing', final_answer: 'done!' }),
    )
    vi.mocked(api.getTrace).mockResolvedValue([
      {
        id: 1,
        session_id: SESSION_ID,
        sequence: 1,
        node: 'planner',
        detail: 'planned',
        level: 'success',
        provider: 'gemini',
        created_at: '2026-08-24T00:00:00Z',
      },
    ] as TraceEvent[])
    renderPage()
    expect(await screen.findByText('do a thing')).toBeInTheDocument()
    expect(screen.getByText('done!')).toBeInTheDocument()
    expect(screen.getByText('planned')).toBeInTheDocument()
  })

  it('sends the first message and refreshes session + trace on success', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getSession).mockResolvedValueOnce(makeSession({ status: 'created' }))
    vi.mocked(api.getTrace).mockResolvedValue([])
    vi.mocked(api.sendMessage).mockResolvedValue(
      makeSession({ status: 'done', task: 'what is 2+2?', final_answer: 'it is 4' }),
    )
    renderPage()

    const input = await screen.findByLabelText(/what should the agent do/i)
    await user.type(input, 'what is 2+2?')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(api.sendMessage).toHaveBeenCalledWith(
      SESSION_ID,
      'what is 2+2?',
      expect.any(AbortSignal),
    )
    expect(await screen.findByText('it is 4')).toBeInTheDocument()
  })

  it('shows an approval modal when the session has a pending action, and approving resolves it', async () => {
    const user = userEvent.setup()
    const pending = {
      id: 'p1',
      session_id: SESSION_ID,
      tool_name: 'notes_store',
      tool_args: { action: 'write', key: 'k', content: 'v' },
      status: 'pending' as const,
      reason: null,
      created_at: '2026-08-24T00:00:00Z',
      decided_at: null,
    }
    vi.mocked(api.getSession).mockResolvedValueOnce(
      makeSession({ status: 'awaiting_approval', task: 'save a note', pending_action: pending }),
    )
    vi.mocked(api.getTrace).mockResolvedValue([])
    vi.mocked(api.approvePendingAction).mockResolvedValue(
      makeSession({ status: 'done', task: 'save a note', final_answer: 'saved' }),
    )
    renderPage()

    expect(await screen.findByRole('dialog')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Approve' }))

    expect(api.approvePendingAction).toHaveBeenCalledWith('p1', expect.any(AbortSignal))
    expect(await screen.findByText('saved')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('rejects with the typed reason and refreshes', async () => {
    const user = userEvent.setup()
    const pending = {
      id: 'p1',
      session_id: SESSION_ID,
      tool_name: 'notes_store',
      tool_args: { action: 'write' },
      status: 'pending' as const,
      reason: null,
      created_at: '2026-08-24T00:00:00Z',
      decided_at: null,
    }
    vi.mocked(api.getSession).mockResolvedValueOnce(
      makeSession({ status: 'awaiting_approval', task: 'save a note', pending_action: pending }),
    )
    vi.mocked(api.getTrace).mockResolvedValue([])
    vi.mocked(api.rejectPendingAction).mockResolvedValue(
      makeSession({ status: 'failed', task: 'save a note', final_answer: 'not saved' }),
    )
    renderPage()

    await screen.findByRole('dialog')
    await user.type(screen.getByLabelText(/reason/i), 'not needed')

    await user.click(screen.getByRole('button', { name: 'Reject' }))

    expect(api.rejectPendingAction).toHaveBeenCalledWith(
      'p1',
      'not needed',
      expect.any(AbortSignal),
    )
    expect(await screen.findByText('not saved')).toBeInTheDocument()
  })

  it('shows an error in the approval modal when the decision request fails, without closing it', async () => {
    const user = userEvent.setup()
    const pending = {
      id: 'p1',
      session_id: SESSION_ID,
      tool_name: 'notes_store',
      tool_args: { action: 'write' },
      status: 'pending' as const,
      reason: null,
      created_at: '2026-08-24T00:00:00Z',
      decided_at: null,
    }
    vi.mocked(api.getSession).mockResolvedValue(
      makeSession({ status: 'awaiting_approval', task: 'save a note', pending_action: pending }),
    )
    vi.mocked(api.getTrace).mockResolvedValue([])
    vi.mocked(api.approvePendingAction).mockRejectedValue(
      new Error("pending action already approved, not 'pending'"),
    )
    renderPage()

    await screen.findByRole('dialog')
    await user.click(screen.getByRole('button', { name: 'Approve' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('already approved')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('aborts an in-flight action when the page unmounts', async () => {
    const user = userEvent.setup()
    let actionSignal: AbortSignal | undefined
    vi.mocked(api.getSession).mockResolvedValueOnce(makeSession({ status: 'created' }))
    vi.mocked(api.getTrace).mockResolvedValue([])
    vi.mocked(api.sendMessage).mockImplementation((_id, _content, signal) => {
      actionSignal = signal
      return new Promise(() => {})
    })
    const rendered = renderPage()

    await user.type(await screen.findByLabelText(/what should the agent do/i), 'keep working')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(actionSignal?.aborted).toBe(false)

    rendered.unmount()
    expect(actionSignal?.aborted).toBe(true)
  })

  it('rejects an invalid session id locally without issuing reads', () => {
    renderPage('/sessions/not-a-uuid')
    expect(screen.getByRole('heading', { name: 'Invalid session link' })).toBeInTheDocument()
    expect(api.getSession).not.toHaveBeenCalled()
    expect(api.getTrace).not.toHaveBeenCalled()
  })

  it('keeps a successful decision closed when the trace refresh fails', async () => {
    const user = userEvent.setup()
    const pending = {
      id: 'p1',
      session_id: SESSION_ID,
      tool_name: 'notes_store',
      tool_args: { action: 'write' },
      status: 'pending' as const,
      reason: null,
      created_at: '2026-08-24T00:00:00Z',
      decided_at: null,
    }
    vi.mocked(api.getSession).mockResolvedValueOnce(
      makeSession({ status: 'awaiting_approval', task: 'save', pending_action: pending }),
    )
    vi.mocked(api.getTrace)
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error('trace unavailable'))
    vi.mocked(api.approvePendingAction).mockResolvedValue(
      makeSession({ status: 'done', task: 'save', final_answer: 'saved' }),
    )
    renderPage()

    await screen.findByRole('dialog')
    await user.click(screen.getByRole('button', { name: 'Approve' }))

    expect(await screen.findByText('saved')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('trace unavailable')
  })
})
