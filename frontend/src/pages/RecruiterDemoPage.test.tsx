import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { RecruiterDemoPage } from './RecruiterDemoPage'

describe('RecruiterDemoPage', () => {
  it('shows every resilience behavior before the approval gate', () => {
    render(
      <MemoryRouter>
        <RecruiterDemoPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('Multi-step research')).toBeInTheDocument()
    expect(screen.getByText('Provider failover')).toBeInTheDocument()
    expect(screen.getByText('Tool recovery')).toBeInTheDocument()
    expect(screen.getByText('Injection defense')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Human approval required' })).toBeInTheDocument()
    expect(screen.getByText(/Gemini returned 503/)).toBeInTheDocument()
    expect(screen.getByText(/PROMPT INJECTION BLOCKED/)).toBeInTheDocument()
    expect(screen.getByText(/upstream search timed out/)).toBeInTheDocument()
  })

  it('resumes the run only after explicit approval', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <RecruiterDemoPage />
      </MemoryRouter>,
    )

    expect(screen.queryByText(/notes_store wrote/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Approve and resume' }))

    expect(screen.getByRole('heading', { name: 'Run completed safely' })).toBeInTheDocument()
    expect(screen.getByText(/notes_store wrote/)).toBeInTheDocument()
    expect(screen.getByText('COMPLETED')).toBeInTheDocument()
  })
})
