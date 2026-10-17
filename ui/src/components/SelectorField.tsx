import type { AsyncState } from '../hooks/useAsync'
import { ApiError } from '../api/client'

export interface SelectOption {
  value: string
  label: string
}

interface Props<T> {
  id: string
  label: string
  placeholder: string
  emptyMessage: string
  state: AsyncState<T> & { reload: () => void }
  /** Null while the controlling selector above has no value. */
  options: SelectOption[] | null
  value: string | null
  onChange: (value: string | null) => void
}

export function SelectorField<T>({ id, label, placeholder, emptyMessage, state, options, value, onChange }: Props<T>) {
  const loading = state.status === 'loading'
  const failed = state.status === 'error'
  const empty = state.status === 'success' && options !== null && options.length === 0
  const disabled = options === null || loading || failed || empty

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value ?? ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value === '' ? null : event.target.value)}
      >
        <option value="">{placeholder}</option>
        {(options ?? []).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {loading && (
        <p className="status" role="status">
          Loading…
        </p>
      )}
      {empty && <p className="status">{emptyMessage}</p>}
      {failed && (
        <p className="status error" role="alert">
          {state.error instanceof ApiError ? state.error.message : 'Something went wrong.'}{' '}
          <button type="button" onClick={state.reload}>
            Retry
          </button>
        </p>
      )}
    </div>
  )
}
