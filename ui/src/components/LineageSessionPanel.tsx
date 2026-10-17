import type { ApiClient } from '../api/client'
import { ApiError } from '../api/client'
import type { TargetRef } from '../api/types'
import { useAsync } from '../hooks/useAsync'

interface Props {
  client: ApiClient
  target: TargetRef | null
  title: string | null
}

/** Loads the data a lineage walkthrough starts from; the panels that render it come later. */
export function LineageSessionPanel({ client, target, title }: Props) {
  const state = useAsync(
    target
      ? async (signal) => {
          const [upstream, sources] = await Promise.all([
            client.rootChoices(target, signal),
            client.ultimateSources(target, signal),
          ])
          return { choices: upstream.choices, sources: sources.terminal_sources }
        }
      : null,
    target ? `${target.project}:${target.objectId}:${target.columnId}` : 'none',
  )

  if (state.status === 'idle') {
    return <p className="placeholder">Select a project, target object and target column to start.</p>
  }
  if (state.status === 'loading') {
    return (
      <p className="status" role="status">
        Loading lineage…
      </p>
    )
  }
  if (state.status === 'error') {
    return (
      <p className="status error" role="alert">
        {state.error instanceof ApiError ? state.error.message : 'Something went wrong.'}{' '}
        <button type="button" onClick={state.reload}>
          Retry
        </button>
      </p>
    )
  }
  return (
    <section aria-label="Lineage session">
      <h2>{title}</h2>
      <dl>
        <dt>Immediate upstream choices</dt>
        <dd data-testid="choice-count">{state.data.choices.length}</dd>
        <dt>Ultimate sources</dt>
        <dd data-testid="source-count">{state.data.sources.length}</dd>
      </dl>
    </section>
  )
}
