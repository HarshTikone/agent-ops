import { useState, type FormEvent } from 'react'
import { clearOperatorKey, getOperatorKey, setOperatorKey } from '../lib/api'

export function OperatorKeyControl() {
  const [draft, setDraft] = useState('')
  const [configured, setConfigured] = useState(() => Boolean(getOperatorKey()))

  const save = (event: FormEvent) => {
    event.preventDefault()
    const normalized = draft.trim()
    if (!normalized) return
    setOperatorKey(normalized)
    setDraft('')
    setConfigured(true)
  }

  const clear = () => {
    clearOperatorKey()
    setDraft('')
    setConfigured(false)
  }

  return (
    <form onSubmit={save} className="flex items-center gap-2" aria-label="Operator credentials">
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
    </form>
  )
}
