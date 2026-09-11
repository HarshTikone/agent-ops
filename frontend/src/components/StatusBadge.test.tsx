import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'
import type { SessionStatus } from '../lib/api'

describe('StatusBadge', () => {
  const cases: [SessionStatus, string][] = [
    ['created', 'New'],
    ['running', 'Running'],
    ['awaiting_approval', 'Needs approval'],
    ['done', 'Done'],
    ['degraded', 'No summary'],
    ['failed', 'Failed'],
  ]

  it.each(cases)('renders %s as "%s"', (status, label) => {
    render(<StatusBadge status={status} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('does not present a degraded run as a success', () => {
    const { rerender } = render(<StatusBadge status="done" />)
    const doneClass = screen.getByText('Done').className
    rerender(<StatusBadge status="degraded" />)
    const degradedClass = screen.getByText('No summary').className
    expect(degradedClass).not.toBe(doneClass)
  })

  it('gives awaiting_approval and failed visually distinct colors', () => {
    const { rerender } = render(<StatusBadge status="awaiting_approval" />)
    const amberClass = screen.getByText('Needs approval').className
    rerender(<StatusBadge status="failed" />)
    const redClass = screen.getByText('Failed').className
    expect(amberClass).not.toBe(redClass)
  })
})
