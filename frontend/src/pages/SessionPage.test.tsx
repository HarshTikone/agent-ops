import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionPage } from './SessionPage'
import * as api from '../lib/api'
import type { Message, Session, TraceEvent } from '../lib/api'

const SESSION_ID = '91255bea-f210-48b0-a3df-8dea7938d645'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof api>('../lib/api')
  return {
    ...actual,
    getSession: vi.fn(),
    getTrace: vi.fn(),
    getMessages: vi.fn(),
    sendMessage: vi.fn(),
    approvePendingAction: vi.fn(),
    rejectPendingAction: vi.fn(),
  }
})

function makeSession(overrides: Partial<Session> = {}): Session {
  const task = overrides.task ?? ''
  return {
    id: SESSION_ID,
    task,
    title: task || null,
    status: 'created',
    final_answer: null,
    archived_at: null,
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
    pending_action: null,
    ...overrides,
  }
}

function makeConversation(userContent: string, assistantContent: string): Message[] {
  return [
    {
      id: 'm1',
      session_id: SESSION_ID,
      role: 'user',
      content: userContent,
      created_at: '2026-08-24T00:00:00Z',
    },
    {
      id: 'm2',
      session_id: SESSION_ID,
      role: 'assistant',
      content: assistantContent,
      created_at: '2026-08-24T00:00:01Z',
    },
  ]
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
    vi.mocked(api.getMessages).mockReturnValue(new Promise(() => {}))
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
    vi.mocked(api.getMessages).mockResolvedValue([])
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('session not found')
  })

  it('renders the chat panel and trace once loaded', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      makeSession({ status: 'done', task: 'do a thing', final_answer: 'done!' }),
    )
    vi.mocked(api.getMessages).mockResolvedValue(makeConversation('do a thing', 'done!'))
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
        started_at: '2026-08-24T00:00:00Z',
        duration_ms: 850,
        tokens_in: 120,
        tokens_out: 40,
        cost_usd: '0.000123',
      },
    ] as TraceEvent[])
    renderPage()
    expect(await screen.findByText('do a thing')).toBeInTheDocument()
    expect(screen.getByText('done!')).toBeInTheDocument()
    expect(screen.getByText('planned')).toBeInTheDocument()
  })

  it('shows run totals summarized from timed trace events, and an em dash when nothing was measured', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      makeSession({ status: 'done', task: 'do a thing', final_answer: 'done!' }),
    )
    vi.mocked(api.getMessages).mockResolvedValue(makeConversation('do a thing', 'done!'))
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
        started_at: '2026-08-24T00:00:00Z',
        duration_ms: 800,
        tokens_in: 100,
        tokens_out: 50,
        cost_usd: '0.000200',
      },
      {
        id: 2,
        session_id: SESSION_ID,
        sequence: 2,
        node: 'approval_gate',
        detail: 'step=0 tool=notes_store APPROVED',
        level: 'success',
        provider: null,
        created_at: '2026-08-24T00:01:00Z',
        started_at: null,
        duration_ms: null,
        tokens_in: null,
        tokens_out: null,
        cost_usd: null,
      },
    ] as TraceEvent[])
    renderPage()

    const totals = await screen.findByLabelText('Run totals')
    expect(totals).toHaveTextContent('800ms')
    expect(totals).toHaveTextContent('150')
    expect(totals).toHaveTextContent('$0.0002')
  })

  it('shows an em dash for every run total when no trace event measured anything', async () => {
    vi.mocked(api.getSession).mockResolvedValue(
      makeSession({ status: 'running', task: 'in progress' }),
    )
    vi.mocked(api.getTrace).mockResolvedValue([])
    vi.mocked(api.getMessages).mockResolvedValue([])
    renderPage()

    const totals = await screen.findByLabelText('Run totals')
    expect(totals.textContent?.match(/—/g)).toHaveLength(3)
  })

  it('sends the first message and refreshes session + trace on success', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getSession).mockResolvedValueOnce(makeSession({ status: 'created' }))
    vi.mocked(api.getTrace).mockResolvedValue([])
    vi.mocked(api.getMessages).mockResolvedValue(makeConversation('what is 2+2?', 'it is 4'))
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
    vi.mocked(api.getMessages)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce(makeConversation('save a note', 'saved'))
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
    vi.mocked(api.getMessages)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce(makeConversation('save a note', 'not saved'))
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
    vi.mocked(api.getMessages).mockResolvedValue([])
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
    vi.mocked(api.getMessages).mockResolvedValue([])
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
    expect(api.getMessages).not.toHaveBeenCalled()
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
    vi.mocked(api.getMessages)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce(makeConversation('save', 'saved'))
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
