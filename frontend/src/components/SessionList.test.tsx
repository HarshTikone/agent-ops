import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { SessionList } from './SessionList'
import type { Session } from '../lib/api'

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: 's1',
    task: 'what is 2+2?',
    status: 'done',
    final_answer: 'it is 4',
    created_at: '2026-08-24T00:00:00Z',
    updated_at: '2026-08-24T00:00:00Z',
    pending_action: null,
    ...overrides,
  }
}

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('SessionList', () => {
  it('shows an empty state with no sessions', () => {
    renderWithRouter(<SessionList sessions={[]} />)
    expect(screen.getByText(/no sessions yet/i)).toBeInTheDocument()
  })

  it('renders one link per session, showing its task and status', () => {
    renderWithRouter(
      <SessionList
        sessions={[
          makeSession({ id: 's1', task: 'first task', status: 'done' }),
          makeSession({ id: 's2', task: 'second task', status: 'awaiting_approval' }),
        ]}
      />,
    )
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('href', '/sessions/s1')
    expect(links[0]).toHaveTextContent('first task')
    expect(screen.getByText('Needs approval')).toBeInTheDocument()
  })

  it('shows a placeholder for a session with no task yet', () => {
    renderWithRouter(<SessionList sessions={[makeSession({ task: '', status: 'created' })]} />)
    expect(screen.getByText('Untitled session')).toBeInTheDocument()
  })
})
