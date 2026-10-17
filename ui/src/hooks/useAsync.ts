import { useCallback, useEffect, useState } from 'react'

export type AsyncState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: Error }

/** Runs `load` whenever `key` changes; a null `load` means nothing to fetch. Stale responses are dropped. */
export function useAsync<T>(
  load: ((signal: AbortSignal) => Promise<T>) | null,
  key: string,
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ status: load ? 'loading' : 'idle' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!load) {
      setState({ status: 'idle' })
      return
    }
    const controller = new AbortController()
    setState({ status: 'loading' })
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: 'success', data })
      },
      (error: unknown) => {
        if (controller.signal.aborted) return
        setState({ status: 'error', error: error instanceof Error ? error : new Error(String(error)) })
      },
    )
    return () => controller.abort()
    // `key` stands for the inputs of `load`; the function identity changes every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt])

  const reload = useCallback(() => setAttempt((n) => n + 1), [])
  return { ...state, reload }
}
