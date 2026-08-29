import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { getOperatorKey } from '../lib/api'
import { OperatorKeyControl } from './OperatorKeyControl'

describe('OperatorKeyControl', () => {
  beforeEach(() => sessionStorage.clear())

  it('stores and clears the runtime key in session storage', async () => {
    const user = userEvent.setup()
    render(<OperatorKeyControl />)

    await user.type(screen.getByLabelText('Operator key'), '  secret-value  ')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(getOperatorKey()).toBe('secret-value')
    expect(screen.getByPlaceholderText('Operator key saved')).toHaveValue('')

    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(getOperatorKey()).toBe('')
  })
})
