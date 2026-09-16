import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { SessionList } from './SessionList'
import type { Session } from '../lib/api'

function makeSession(overrides: Partial<Session> = {}): Session {
  const task = overrides.task ?? 'what is 2+2?'
  return {
    id: 's1',
    task,
    title: task,
    status: 'done',
    final_answer: 'it is 4',
    archived_at: null,
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

  it('shows the stable title, not a follow-up turn task drift (WP5, ADR-036)', () => {
    renderWithRouter(
      <SessionList
        sessions={[makeSession({ title: 'first task', task: 'a much later follow-up' })]}
      />,
    )
    expect(screen.getByRole('heading', { level: 2, name: 'first task' })).toBeInTheDocument()
    expect(screen.queryByText('a much later follow-up')).not.toBeInTheDocument()
  })

  it('shows a placeholder for a session with no task yet', () => {
    renderWithRouter(<SessionList sessions={[makeSession({ task: '', status: 'created' })]} />)
    expect(screen.getByText('Untitled session')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /archive session/i })).not.toBeInTheDocument()
  })

  it('archives a session from its own card without opening the session', async () => {
    const user = userEvent.setup()
    const onArchive = vi.fn()
    renderWithRouter(
      <SessionList
        sessions={[makeSession({ id: 'abcd1234', task: 'first task' })]}
        onArchive={onArchive}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Archive session 1234' }))

    expect(onArchive).toHaveBeenCalledWith('abcd1234')
    // The archive control is a sibling of the card link, never nested inside
    // it, so the card's own open action cannot fire from this click.
    expect(screen.getByRole('link')).toBeInTheDocument()
  })

  it('does not show an archive button without an onArchive handler', () => {
    renderWithRouter(<SessionList sessions={[makeSession()]} />)
    expect(screen.queryByRole('button', { name: /archive session/i })).not.toBeInTheDocument()
  })

  it('shows an Archived tag and a Restore button for an archived session', async () => {
    const user = userEvent.setup()
    const onRestore = vi.fn()
    renderWithRouter(
      <SessionList
        sessions={[
          makeSession({ id: 'abcd1234', task: 'first task', archived_at: '2026-09-16T00:00:00Z' }),
        ]}
        onRestore={onRestore}
      />,
    )

    expect(screen.getByText('Archived')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /archive session/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Restore' }))
    expect(onRestore).toHaveBeenCalledWith('abcd1234')
    expect(screen.getByRole('link')).toBeInTheDocument()
  })

  it('does not show a Restore button for an archived session without an onRestore handler', () => {
    renderWithRouter(
      <SessionList sessions={[makeSession({ archived_at: '2026-09-16T00:00:00Z' })]} />,
    )
    expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument()
  })

  it('shows the last four characters of the id as the card kicker', () => {
    renderWithRouter(<SessionList sessions={[makeSession({ id: 'ff00abcd' })]} />)
    expect(screen.getByText(/SESSION · ABCD/)).toBeInTheDocument()
  })
})
