import { useState, type FormEvent } from 'react'
import {
  clearOperatorKey,
  getOperatorKey,
  MIN_OPERATOR_KEY_BYTES,
  operatorKeyByteLength,
  setOperatorKey,
} from '../lib/api'

export function OperatorKeyControl() {
  const [draft, setDraft] = useState('')
  const [configured, setConfigured] = useState(() => Boolean(getOperatorKey()))
  const [error, setError] = useState<string | null>(null)

  const save = (event: FormEvent) => {
    event.preventDefault()
    const normalized = draft.trim()
    if (!normalized) return
    if (operatorKeyByteLength(normalized) < MIN_OPERATOR_KEY_BYTES) {
      setError('The operator key must contain at least 32 bytes.')
      return
    }
    if (!setOperatorKey(normalized)) {
      setError('Could not save the operator key in this browser.')
      return
    }
    setDraft('')
    setConfigured(true)
    setError(null)
  }

  const clear = () => {
    if (!clearOperatorKey()) {
      setConfigured(Boolean(getOperatorKey()))
      setError('Could not clear the operator key from this browser.')
      return
    }
    setDraft('')
    setConfigured(false)
    setError(null)
  }

  return (
    <form
      onSubmit={save}
      className="flex flex-wrap items-center gap-2"
      aria-label="Operator credentials"
    >
      <label htmlFor="operator-key" className="sr-only">
        Operator key
      </label>
      <input
        id="operator-key"
        type="password"
        autoComplete="off"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={configured ? 'Operator key saved' : 'Operator key'}
        aria-describedby={error ? 'operator-key-error' : undefined}
        aria-invalid={Boolean(error)}
        className="input w-36 py-1 text-xs"
      />
      <button
        type="submit"
        disabled={!draft.trim()}
        className="btn btn-secondary px-3 py-1 text-xs"
      >
        Save
      </button>
      {configured && (
        <button
          type="button"
          onClick={clear}
          className="btn btn-ghost px-2 py-1 text-xs text-[var(--color-danger)]"
        >
          Clear
        </button>
      )}
      {error && (
        <span
          id="operator-key-error"
          role="alert"
          className="w-full text-xs text-[var(--color-danger)]"
        >
          {error}
        </span>
      )}
    </form>
  )
}
