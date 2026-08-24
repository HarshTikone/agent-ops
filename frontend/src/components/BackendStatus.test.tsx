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

  it('shows ready in green with no missing checks when the backend is fully configured', async () => {
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
    const statusText = await screen.findByText(/Backend status: ready/)
    expect(statusText).toHaveClass('text-green-500')
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('shows degraded in amber (not red) when only the OpenRouter fallback is unconfigured', async () => {
    // Per ADR-009: Gemini + Supabase + database present means every request
    // can still be served — missing only the failover safety net is a
    // warning, not the same "broken" signal as not_ready.
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'degraded',
        checks: {
          gemini_api_key_set: true,
          openrouter_api_key_set: false,
          supabase_configured: true,
          database_configured: true,
        },
      }),
    })
    render(<BackendStatus />)
    const statusText = await screen.findByText(/Backend status: degraded/)
    expect(statusText).toHaveClass('text-amber-500')
    const missingList = screen.getByText('openrouter_api_key_set missing')
    expect(missingList).toBeInTheDocument()
    expect(missingList.closest('ul')).toHaveClass('text-amber-500')
  })

  it('shows not_ready in red and lists exactly the missing config keys', async () => {
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
    const statusText = await screen.findByText(/Backend status: not_ready/)
    expect(statusText).toHaveClass('text-red-500')
    const missingItem = screen.getByText('openrouter_api_key_set missing')
    expect(missingItem).toBeInTheDocument()
    // The fix: the missing-checks list now matches the header's color
    // instead of always being amber regardless of status (flagged Day 1).
    expect(missingItem.closest('ul')).toHaveClass('text-red-500')
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
