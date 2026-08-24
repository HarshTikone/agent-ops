import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionListPage } from './SessionListPage'
import * as api from '../lib/api'
import type { Session } from '../lib/api'

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof api>('../lib/api')
  return { ...actual, listSessions: vi.fn(), createSession: vi.fn() }
})

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: 's1',
    task: 'a task',
    status: 'done',
    final_answer: 'an answer',
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
})
