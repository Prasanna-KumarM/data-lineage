import { useState } from 'react'
import { ApiError, type ApiClient } from '../api/client'
import type { TargetColumn, TargetObject, TargetRef, TerminalSource } from '../api/types'
import { useAsync, type AsyncState } from '../hooks/useAsync'
import { ChoiceList } from './ChoiceList'
import { SourceList } from './SourceList'
import { TargetPanel } from './TargetPanel'

interface Props {
  client: ApiClient
  target: TargetRef | null
  object: TargetObject | undefined
  column: TargetColumn | undefined
  allObjects: TargetObject[]
}

export function LineageWorkspace({ client, target, object, column, allObjects }: Props) {
  if (!target || !object || !column) {
    return <p className="placeholder">Select a project, target object and target column to start.</p>
  }
  const key = `${target.project}:${target.objectId}:${target.columnId}`
  // Keyed so that choosing another target discards the previous selection.
  return (
    <Session key={key} client={client} target={target} object={object} column={column} allObjects={allObjects} sessionKey={key} />
  )
}

function Failure({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <p className="status error" role="alert">
      {error instanceof ApiError ? error.message : 'Something went wrong.'}{' '}
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </p>
  )
}

function Loading({ text }: { text: string }) {
  return (
    <p className="status" role="status">
      {text}
    </p>
  )
}

function Session({
  client,
  target,
  object,
  column,
  allObjects,
  sessionKey,
}: Props & { target: TargetRef; object: TargetObject; column: TargetColumn; sessionKey: string }) {
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)

  const session = useAsync(
    async (signal) => {
      const [upstream, sources] = await Promise.all([
        client.rootChoices(target, signal),
        client.ultimateSources(target, signal),
      ])
      return { choices: upstream.choices, sources: sources.terminal_sources }
    },
    sessionKey,
  )

  const branchSources = useAsync(
    selectedStepId ? async (signal) => (await client.ultimateSources(target, signal, selectedStepId)).terminal_sources : null,
    `${sessionKey}:${selectedStepId}`,
  )

  const sources: AsyncState<TerminalSource[]> =
    selectedStepId === null
      ? session.status === 'success'
        ? { status: 'success', data: session.data.sources }
        : session
      : branchSources

  return (
    <div className="workspace" role="region" aria-label="Lineage session">
      <TargetPanel project={target.project} object={object} allObjects={allObjects} column={column} />

      <section className="panel" aria-label="Upstream choices">
        <h2 className="panel-title">Upstream choices</h2>
        {session.status === 'loading' && <Loading text="Loading lineage…" />}
        {session.status === 'error' && <Failure error={session.error} onRetry={session.reload} />}
        {session.status === 'success' && (
          <ChoiceList choices={session.data.choices} selectedStepId={selectedStepId} onSelect={setSelectedStepId} />
        )}
      </section>

      <section className="panel" aria-label="Ultimate sources">
        <h2 className="panel-title">Ultimate sources</h2>
        {sources.status === 'loading' && <Loading text="Loading sources…" />}
        {sources.status === 'error' && session.status !== 'error' && (
          <Failure error={sources.error} onRetry={selectedStepId ? branchSources.reload : session.reload} />
        )}
        {sources.status === 'success' && <SourceList sources={sources.data} />}
      </section>
    </div>
  )
}
