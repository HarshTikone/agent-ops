import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
    // Prevent BackendStatus's real fetch call from firing during this
    // smoke test — its own behavior is covered by BackendStatus.test.tsx.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )
  })

  it('renders a home link for the Agent Ops brand', () => {
    render(<App />)
    expect(screen.getByRole('link', { name: 'Agent Ops home' })).toHaveAttribute('href', '/')
  })

  it('renders a useful not-found page for an unknown route', () => {
    window.history.pushState({}, '', '/does-not-exist')
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Return to all sessions' })).toHaveAttribute(
      'href',
      '/',
    )
  })
})
