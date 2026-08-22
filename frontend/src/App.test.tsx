import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    // Prevent BackendStatus's real fetch call from firing during this
    // smoke test — its own behavior is covered by BackendStatus.test.tsx.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )
  })

  it('renders the Agent Ops heading', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Agent Ops' })).toBeInTheDocument()
  })
})
