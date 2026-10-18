import { ApiError } from '../api/client'

export function ErrorNotice({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <p className="status error" role="alert">
      {error instanceof ApiError ? error.message : 'Something went wrong.'}{' '}
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </p>
  )
}

export function LoadingNotice({ text }: { text: string }) {
  return (
    <p className="status" role="status">
      {text}
    </p>
  )
}
