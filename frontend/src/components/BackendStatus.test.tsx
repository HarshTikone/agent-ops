import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BackendStatus } from './BackendStatus'

describe('BackendStatus', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a loading state before the response resolves', () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}))
    render(<BackendStatus />)
    expect(screen.getByRole('status')).toHaveTextContent('Checking backend connection')
  })

  it('shows ready with no missing checks when the backend is fully configured', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'ready',
        checks: {
          gemini_api_key_set: true,
          openrouter_api_key_set: true,
          supabase_configured: true,
          database_configured: true,
        },
      }),
    })
    render(<BackendStatus />)
    await waitFor(() => expect(screen.getByText(/Backend status: ready/)).toBeInTheDocument())
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('lists exactly the missing config keys when partially configured', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'not_ready',
        checks: {
          gemini_api_key_set: true,
          openrouter_api_key_set: false,
          supabase_configured: false,
          database_configured: true,
        },
      }),
    })
    render(<BackendStatus />)
    await waitFor(() => expect(screen.getByText(/Backend status: not_ready/)).toBeInTheDocument())
    expect(screen.getByText('openrouter_api_key_set missing')).toBeInTheDocument()
    expect(screen.getByText('supabase_configured missing')).toBeInTheDocument()
    expect(screen.queryByText(/gemini_api_key_set missing/)).not.toBeInTheDocument()
  })

  it('shows an error state — the shown failure mode — when the backend is unreachable', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new TypeError('Failed to fetch'))
    render(<BackendStatus />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('Backend unreachable')
  })

  it('surfaces a non-2xx response as the same error state', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, status: 503 })
    render(<BackendStatus />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('status 503')
  })
})
