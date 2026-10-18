import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ApiError, bindProject, type ApiClient } from '../api/client'
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
  client: unboundClient,
  target,
  object,
  column,
  allObjects,
  sessionKey,
}: Props & { target: TargetRef; object: TargetObject; column: TargetColumn; sessionKey: string }) {
  // Step and relation requests carry no project, so every request of this session names it.
  const client = useMemo(() => bindProject(unboundClient, target.project), [unboundClient, target.project])
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
  const endpointOf = (c: { source_object_name: string; source_column_name: string }) => `${c.source_object_name}.${c.source_column_name}`
  const targetLabel = `${object.object_name}.${column.column_name}`
  const endpoint = parent ? endpointOf(parent) : targetLabel
  const backLabel = depth === 0 ? null : depth === 1 ? targetLabel : endpointOf(nav.path[depth - 2])
  const allTerminal = list.status === 'success' && list.data.length > 0 && list.data.every((c) => !c.has_more_upstream)
  const goBack = useCallback(() => dispatch({ type: 'back' }), [])
  const goNext = () => selected && canNext && dispatch({ type: 'next', choice: selected })

  // The ultimate source itself is not a step of the path: it has its own panel.
  const pathSelected = selected?.has_more_upstream ? selected : undefined
  const remaining = remainingDepth.status === 'success' ? remainingDepth.data : null
  const stepText = (() => {
    if (allTerminal) return 'Ultimate sources'
    const base = `Step ${depth + 1}`
    if (!pathSelected || !remaining || remaining.is_terminal) return base
    const less = (n: number | null) => Math.max(0, (n ?? 1) - 1)
    const min = depth + 1 + less(remaining.remaining_hops_exact ?? remaining.remaining_hops_min)
    const max = depth + 1 + less(remaining.remaining_hops_exact ?? remaining.remaining_hops_max)
    return min === max ? `${base} of ${min}` : `${base} of ${min}–${max}`
  })()

  const instruction = (() => {
    if (list.status !== 'success') return 'Loading the next mappings…'
    if (allTerminal) {
      return depth === 0
        ? 'This column maps directly to its ultimate sources; there is nothing further to follow.'
        : 'You have reached an ultimate source. Press Back to try another branch.'
    }
    if (!selected) return 'Pick the mapping you want to follow, then press Next.'
    if (canNext) return `Press Next to see where ${endpointOf(selected)} comes from.`
    return `${endpointOf(selected)} is an ultimate source. Pick another mapping or press Back.`
  })()

  // Arrow keys step through the path unless the user is typing or a dialog is open.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || detailStepId) return
      const el = event.target as HTMLElement | null
      if (el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return
      if (event.key === 'ArrowLeft' && depth > 0) goBack()
      else if (event.key === 'ArrowRight' && selected && canNext) dispatch({ type: 'next', choice: selected })
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [depth, selected, canNext, detailStepId, goBack])

  return (
    <div className="workspace" role="region" aria-label="Lineage session">
      <TargetPanel project={target.project} object={object} allObjects={allObjects} column={column} />

      <section className="panel choices-panel" aria-label="Upstream choices">
        <div className="walk-bar">
          <div className="panel-head">
            <h2 className="panel-title">Where does this come from?</h2>
            <span className="hop-badge">{stepText}</span>
          </div>
          <p className="walk-instruction" aria-live="polite">
            {instruction}
          </p>
          <div className="walk-controls">
            <button type="button" className="walk-btn" onClick={goBack} disabled={depth === 0}>
              <span className="walk-btn-main">
                <span aria-hidden="true">‹</span> Back
              </span>
              <span className="walk-btn-sub">{backLabel ? `to ${backLabel}` : 'Start of path'}</span>
            </button>
            <HopRail path={nav.path} selected={pathSelected} depth={remainingDepth} onJump={(d) => dispatch({ type: 'jump', depth: d })} />
            <button
              type="button"
              className="walk-btn primary"
              onClick={goNext}
              disabled={!canNext}
              title={selected && !canNext ? 'Nothing further upstream' : undefined}
            >
              <span className="walk-btn-main">
                Next <span aria-hidden="true">›</span>
              </span>
              <span className="walk-btn-sub">
                {selected ? (canNext ? `Go into ${endpointOf(selected)}` : 'Nothing further upstream') : 'Pick a mapping first'}
              </span>
            </button>
          </div>
        </div>

        <div className="block">
          <h3 className="block-title">Your path</h3>
          <Breadcrumb targetLabel={targetLabel} path={nav.path} selected={pathSelected} />
        </div>

        <div className="block">
          <h3 className="block-title">Pick one to follow</h3>
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
