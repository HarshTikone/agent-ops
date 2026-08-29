import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TraceViewer } from './TraceViewer'
import type { TraceEvent } from '../lib/api'

function event(overrides: Partial<TraceEvent>): TraceEvent {
  return {
    id: 1,
    session_id: 's1',
    sequence: 1,
    node: 'planner',
    detail: 'provider=gemini steps=[]',
    level: 'info',
    provider: null,
    created_at: '2026-08-24T00:00:00Z',
    ...overrides,
  }
}

describe('TraceViewer', () => {
  it('shows an empty state with no events', () => {
    render(<TraceViewer events={[]} />)
    expect(screen.getByText(/no trace events yet/i)).toBeInTheDocument()
  })

  it('renders one list item per event, in order, with its node label', () => {
    render(
      <TraceViewer
        events={[
          event({ id: 1, node: 'planner', detail: 'planning' }),
          event({ id: 2, node: 'tool_call', detail: 'OK: 4183' }),
        ]}
      />,
    )
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('PLANNER')
    expect(items[0]).toHaveTextContent('planning')
    expect(items[1]).toHaveTextContent('TOOL CALL')
  })

  it('shows the provider when present', () => {
    render(<TraceViewer events={[event({ provider: 'gemini' })]} />)
    expect(screen.getByText('via gemini')).toBeInTheDocument()
  })

  it('does not show a provider tag when absent', () => {
    render(<TraceViewer events={[event({ provider: null })]} />)
    expect(screen.queryByText(/^via /)).not.toBeInTheDocument()
  })

  it('uses the structured level before the legacy detail-text fallback', () => {
    render(
      <TraceViewer
        events={[event({ level: 'error', detail: 'neutral wording with no legacy marker' })]}
      />,
    )
    expect(screen.getByRole('listitem')).toHaveAttribute('data-tone', 'error')
  })

  it('colors a transient tool failure as a warning, not an error', () => {
    render(
      <TraceViewer
        events={[event({ node: 'tool_call', detail: 'FAILED (transient): simulated blip' })]}
      />,
    )
    expect(screen.getByRole('listitem')).toHaveAttribute('data-tone', 'warning')
  })

  it('colors a permanent tool failure as an error', () => {
    render(
      <TraceViewer
        events={[event({ node: 'tool_call', detail: 'FAILED (permanent): bad expression' })]}
      />,
    )
    expect(screen.getByRole('listitem')).toHaveAttribute('data-tone', 'error')
  })

  it('colors a rejected approval as an error', () => {
    render(
      <TraceViewer
        events={[event({ node: 'approval_gate', detail: 'step=0 tool=notes_store REJECTED' })]}
      />,
    )
    expect(screen.getByRole('listitem')).toHaveAttribute('data-tone', 'error')
  })

  it('colors an approved gate and a successful tool call as success', () => {
    render(
      <TraceViewer
        events={[
          event({ id: 1, node: 'approval_gate', detail: 'step=0 tool=notes_store APPROVED' }),
          event({ id: 2, node: 'tool_call', detail: 'OK: saved note' }),
        ]}
      />,
    )
    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveAttribute('data-tone', 'success')
    expect(items[1]).toHaveAttribute('data-tone', 'success')
  })

  it('gives a retry decision a warning tone, distinct from an unrelated default event', () => {
    render(
      <TraceViewer
        events={[
          event({
            id: 1,
            node: 'decide_next',
            detail: 'step 0 transient failure -> retry (attempt 1/2)',
          }),
          event({ id: 2, node: 'delegate', detail: 'step=0 tool=calculator args={}' }),
        ]}
      />,
    )
    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveAttribute('data-tone', 'warning')
    expect(items[1]).toHaveAttribute('data-tone', 'default')
  })
})
