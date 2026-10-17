import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { ApiError, type ApiClient } from '../api/client'
import type { Choice, TargetColumn, TargetObject, TargetRef } from '../api/types'
import { useAsync, type AsyncState } from '../hooks/useAsync'
import { activeStepId, initialNavigation, navigationReducer } from '../state/navigation'
import { ChoiceList } from './ChoiceList'
import { DetailDrawer } from './DetailDrawer'
import { Breadcrumb, HopRail } from './HopRail'
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
  // Keyed so that choosing another target discards the whole navigation state.
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
  const [nav, dispatch] = useReducer(navigationReducer, initialNavigation)
  const depth = nav.path.length
  const parent = nav.path[depth - 1]
  const parentKey = parent?.step_id ?? 'root'

  // The drawer only describes a mapping; it never changes where the user is in the lineage.
  const [detailStepId, setDetailStepId] = useState<string | null>(null)
  const [developer, setDeveloper] = useState(false)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const closeDetails = useCallback(() => {
    setDetailStepId(null)
    detailTrigger.current?.focus()
  }, [])
  // Moving to another level hides the mapping the drawer was describing.
  useEffect(() => {
    setDetailStepId(null)
  }, [depth])

  // Lists already seen are kept so that Back shows exactly what was there before.
  const listCache = useRef(new Map<string, Choice[]>())
  const cached = listCache.current.get(parentKey)
  const loadedList = useAsync<Choice[]>(
    cached
      ? null
      : async (signal) => {
          const response = parent ? await client.upstream(parent.step_id, signal) : await client.rootChoices(target, signal)
          listCache.current.set(parentKey, response.choices)
          return response.choices
        },
    `${sessionKey}:list:${parentKey}`,
  )
  const list: AsyncState<Choice[]> & { reload: () => void } = cached
    ? { status: 'success', data: cached, reload: loadedList.reload }
    : loadedList

  const allSources = useAsync(
    async (signal) => (await client.ultimateSources(target, signal)).terminal_sources,
    `${sessionKey}:sources`,
  )
  const activeId = activeStepId(nav)
  const branchSources = useAsync(
    activeId ? async (signal) => (await client.ultimateSources(target, signal, activeId)).terminal_sources : null,
    `${sessionKey}:branch:${activeId}`,
  )
  const sources = activeId === null ? allSources : branchSources

  // Remaining depth is only worked out for the branch being followed, never for every card.
  const remainingDepth = useAsync(
    activeId ? (signal) => client.remainingDepth(activeId, signal) : null,
    `${sessionKey}:depth:${activeId}`,
  )

  const selected = list.status === 'success' ? list.data.find((c) => c.step_id === nav.selectedStepId) : undefined
  const canNext = Boolean(selected?.has_more_upstream)
  const endpoint = parent ? `${parent.source_object_name}.${parent.source_column_name}` : `${object.object_name}.${column.column_name}`

  return (
    <div className="workspace" role="region" aria-label="Lineage session">
      <TargetPanel project={target.project} object={object} allObjects={allObjects} column={column} />

      <section className="panel choices-panel" aria-label="Upstream choices">
        <div className="panel-head">
          <h2 className="panel-title">Upstream choices</h2>
          <span className="hop-badge">Hop {depth + 1}</span>
        </div>

        <div className="block">
          <h3 className="block-title">Your path</h3>
          <HopRail path={nav.path} selected={selected} depth={remainingDepth} onJump={(d) => dispatch({ type: 'jump', depth: d })} />
          <Breadcrumb targetLabel={`${object.object_name}.${column.column_name}`} path={nav.path} selected={selected} />
        </div>

        <div className="block">
          <h3 className="block-title">Choose the next mapping</h3>
          <p className="context">
            Upstream of <strong>{endpoint}</strong>
          </p>
          {list.status === 'loading' && <Loading text="Loading lineage…" />}
          {list.status === 'error' && <Failure error={list.error} onRetry={list.reload} />}
          {list.status === 'success' && (
            <ChoiceList
              choices={list.data}
              selectedStepId={nav.selectedStepId}
              detailStepId={detailStepId}
              atRoot={depth === 0}
              onSelect={(stepId) => dispatch({ type: 'select', stepId })}
              onDetails={(stepId, trigger) => {
                detailTrigger.current = trigger
                setDetailStepId(stepId)
              }}
            />
          )}
        </div>

        <div className="block actions">
          <div className="nav-actions">
            <button type="button" onClick={() => dispatch({ type: 'back' })} disabled={depth === 0}>
              Back
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => selected && dispatch({ type: 'next', choice: selected })}
              disabled={!canNext}
              title={selected && !canNext ? 'Nothing further upstream' : undefined}
            >
              Next
            </button>
          </div>
          <p className="action-hint">
            {!selected
              ? 'Select a mapping to continue.'
              : canNext
                ? 'Next moves into the selected mapping.'
                : 'Nothing further upstream from this mapping.'}
          </p>
        </div>
      </section>

      <section className="panel" aria-label="Ultimate sources">
        <h2 className="panel-title">Ultimate sources</h2>
        {sources.status === 'loading' && <Loading text="Loading sources…" />}
        {sources.status === 'error' && list.status !== 'error' && <Failure error={sources.error} onRetry={sources.reload} />}
        {sources.status === 'success' && <SourceList sources={sources.data} />}
      </section>

      {detailStepId && (
        <DetailDrawer
          client={client}
          stepId={detailStepId}
          developer={developer}
          onDeveloperChange={setDeveloper}
          onClose={closeDetails}
        />
      )}
    </div>
  )
}
