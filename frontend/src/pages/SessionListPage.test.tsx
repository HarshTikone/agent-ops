import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionListPage } from './SessionListPage'
import * as api from '../lib/api'
import type { Session } from '../lib/api'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof api>('../lib/api')
  return {
    ...actual,
    listSessions: vi.fn(),
    createSession: vi.fn(),
    archiveSession: vi.fn(),
    restoreSession: vi.fn(),
  }
})

function makeSession(overrides: Partial<Session> = {}): Session {
  const task = overrides.task ?? 'a task'
  return {
    id: 's1',
    task,
    title: task,
    status: 'done',
    final_answer: 'an answer',
    archived_at: null,
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
    pending_action: null,
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<SessionListPage />} />
        <Route path="/sessions/:sessionId" element={<div>Session detail placeholder</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SessionListPage', () => {
  beforeEach(() => {
    vi.mocked(api.listSessions).mockReturnValue(new Promise(() => {}))
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows a loading state before the list resolves', () => {
    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent('Loading sessions')
  })

  it('renders the fetched sessions', async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      makeSession({ id: 's1', task: 'first' }),
      makeSession({ id: 's2', task: 'second' }),
    ])
    renderPage()
    expect(await screen.findByText('first')).toBeInTheDocument()
    expect(screen.getByText('second')).toBeInTheDocument()
  })

  it('shows an error state when the list fails to load', async () => {
    vi.mocked(api.listSessions).mockRejectedValue(new Error('backend unreachable'))
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('backend unreachable')
  })

  it('creates a session and navigates to it when "New session" is clicked', async () => {
    vi.mocked(api.listSessions).mockResolvedValue([])
    vi.mocked(api.createSession).mockResolvedValue(makeSession({ id: 'new-id', status: 'created' }))
    const user = userEvent.setup()
    renderPage()

    await screen.findByText(/no sessions yet/i)
    await user.click(screen.getByRole('button', { name: 'New session' }))

    expect(await screen.findByText('Session detail placeholder')).toBeInTheDocument()
    expect(api.createSession).toHaveBeenCalledWith(expect.any(AbortSignal))
  })

  it('aborts session creation when the page unmounts', async () => {
    vi.mocked(api.listSessions).mockResolvedValue([])
    let requestSignal: AbortSignal | undefined
    vi.mocked(api.createSession).mockImplementation((signal) => {
      requestSignal = signal
      return new Promise(() => {})
    })
    const user = userEvent.setup()
    const rendered = renderPage()

    await screen.findByText(/no sessions yet/i)
    await user.click(screen.getByRole('button', { name: 'New session' }))
    rendered.unmount()

    expect(requestSignal?.aborted).toBe(true)
  })

  it('shows an error and re-enables the button when session creation fails', async () => {
    vi.mocked(api.listSessions).mockResolvedValue([])
    vi.mocked(api.createSession).mockRejectedValue(new Error('rate limited'))
    const user = userEvent.setup()
    renderPage()

    await screen.findByText(/no sessions yet/i)
    await user.click(screen.getByRole('button', { name: 'New session' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('rate limited')
    expect(screen.getByRole('button', { name: 'New session' })).toBeEnabled()
  })

  it('archives a session card and removes it from the (unarchived) list', async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      makeSession({ id: 'aaaa1111', task: 'keep me' }),
      makeSession({ id: 'bbbb2222', task: 'archive me' }),
    ])
    vi.mocked(api.archiveSession).mockResolvedValue(
      makeSession({ id: 'bbbb2222', task: 'archive me', archived_at: '2026-09-16T00:00:00Z' }),
    )
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('archive me')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Archive session 2222' }))

    expect(api.archiveSession).toHaveBeenCalledWith('bbbb2222')
    expect(await screen.findByText('keep me')).toBeInTheDocument()
    expect(screen.queryByText('archive me')).not.toBeInTheDocument()
    // Archiving is list-local: it must not navigate into the session.
    expect(screen.queryByText('Session detail placeholder')).not.toBeInTheDocument()
  })

  it('shows an error and keeps the card when archiving fails', async () => {
    vi.mocked(api.listSessions).mockResolvedValue([makeSession({ id: 'aaaa1111', task: 'mine' })])
    vi.mocked(api.archiveSession).mockRejectedValue(new Error('rate limited'))
    const user = userEvent.setup()
    renderPage()

    await screen.findByText('mine')
    await user.click(screen.getByRole('button', { name: 'Archive session 1111' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('rate limited')
    expect(screen.getByText('mine')).toBeInTheDocument()
  })

  it('fetches archived sessions when the toggle is checked, and lets one be restored', async () => {
    vi.mocked(api.listSessions).mockResolvedValueOnce([
      makeSession({ id: 'aaaa1111', task: 'visible task' }),
    ])
    const user = userEvent.setup()
    renderPage()
    await screen.findByText('visible task')

    vi.mocked(api.listSessions).mockResolvedValueOnce([
      makeSession({ id: 'aaaa1111', task: 'visible task' }),
      makeSession({ id: 'bbbb2222', task: 'archived task', archived_at: '2026-09-16T00:00:00Z' }),
    ])
    await user.click(screen.getByRole('checkbox', { name: 'Show archived sessions' }))

    expect(await screen.findByText('archived task')).toBeInTheDocument()
    expect(api.listSessions).toHaveBeenLastCalledWith(expect.any(AbortSignal), true)
    expect(screen.getByText('Archived')).toBeInTheDocument()

    vi.mocked(api.restoreSession).mockResolvedValue(
      makeSession({ id: 'bbbb2222', task: 'archived task', archived_at: null }),
    )
    await user.click(screen.getByRole('button', { name: 'Restore' }))

    expect(api.restoreSession).toHaveBeenCalledWith('bbbb2222')
    await screen.findByText('archived task')
    expect(screen.queryByText('Archived')).not.toBeInTheDocument()
  })
})
