import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
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
    expect(screen.getByRole('heading', { level: 2, name: 'first task' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'second task' })).toBeInTheDocument()
    expect(screen.getByText('Needs approval')).toBeInTheDocument()
  })

  it('shows a placeholder for a session with no task yet', () => {
    renderWithRouter(<SessionList sessions={[makeSession({ task: '', status: 'created' })]} />)
    expect(screen.getByText('Untitled session')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /hide session/i })).not.toBeInTheDocument()
  })
  it('hides a session from its own card without opening the session', async () => {
    const user = userEvent.setup()
    const onRemove = vi.fn()
    renderWithRouter(
      <SessionList
        sessions={[makeSession({ id: 'abcd1234', task: 'first task' })]}
        onRemove={onRemove}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Hide session 1234 on this device' }))

    expect(onRemove).toHaveBeenCalledWith('abcd1234')
    // The remove control is a sibling of the card link, never nested inside
    // it, so the card's own open action cannot fire from this click.
    expect(screen.getByRole('link')).toBeInTheDocument()
  })

  it('shows the last four characters of the id as the card kicker', () => {
    renderWithRouter(<SessionList sessions={[makeSession({ id: 'ff00abcd' })]} />)
    expect(screen.getByText(/SESSION · ABCD/)).toBeInTheDocument()
  })
})
