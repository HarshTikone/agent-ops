import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getOperatorKey } from '../lib/api'
import { OperatorKeyControl } from './OperatorKeyControl'

describe('OperatorKeyControl', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('stores and clears the runtime key in session storage', async () => {
    const user = userEvent.setup()
    render(<OperatorKeyControl />)

    const key = 'secret-value-that-is-at-least-32-bytes'
    await user.type(screen.getByLabelText('Operator key'), `  ${key}  `)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(getOperatorKey()).toBe(key)
    expect(screen.getByPlaceholderText('Operator key saved')).toHaveValue('')

    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(getOperatorKey()).toBe('')
  })

  it('does not save a short operator key', async () => {
    const user = userEvent.setup()
    render(<OperatorKeyControl />)
    await user.type(screen.getByLabelText('Operator key'), 'too-short')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('at least 32 bytes')
    expect(getOperatorKey()).toBe('')
  })

  it('reports when session storage rejects a valid key', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    const user = userEvent.setup()
    render(<OperatorKeyControl />)
    await user.type(screen.getByLabelText('Operator key'), 'valid-key-that-is-at-least-32-bytes')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save')
    expect(screen.queryByPlaceholderText('Operator key saved')).not.toBeInTheDocument()
  })

  it('reports when an existing key cannot be cleared', async () => {
    sessionStorage.setItem('agent-ops.operator-key', 'valid-key-that-is-at-least-32-bytes')
    const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    const user = userEvent.setup()
    render(<OperatorKeyControl />)
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(remove).toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Could not clear')
    expect(screen.getByRole('button', { name: 'Clear' })).toBeInTheDocument()
  })
})
