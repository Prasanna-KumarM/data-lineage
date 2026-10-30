import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { ApiError, bindProject, type ApiClient } from '../api/client'
import type { Choice, Continuation, TargetColumn, TargetObject, TargetRef } from '../api/types'
import { useAsync, type AsyncState } from '../hooks/useAsync'
import { activeStepId, initialNavigation, navigationReducer } from '../state/navigation'
import { ChoiceList } from './ChoiceList'
import { DetailDrawer } from './DetailDrawer'
import { GraphWalkthrough } from './GraphWalkthrough'
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

export interface Frame {
  key: string
  target: TargetRef
  object: TargetObject
  column: TargetColumn
}

interface SessionCallbacks {
  /** Continue walking in another project's database. */
  onTrack: (cont: Continuation, fromLabel: string) => void
  /** Set when this frame was entered from another project: Back at the start returns there. */
  onLeave?: () => void
  returnTo?: string
  /** Application name of the current frame's project. */
  appName?: string
}

export function LineageWorkspace({ client, target, object, column, allObjects }: Props) {
  const [view, setView] = useState<'list' | 'graph'>('list')
  if (!target || !object || !column) {
    return <p className="placeholder">Select a project, target object and target column to start.</p>
  }
  const key = `${target.project}:${target.objectId}:${target.columnId}`
  // Keyed so that choosing another target discards the frames as well as the navigation state.
  return <Framed key={key} client={client} target={target} object={object} column={column} allObjects={allObjects} view={view} setView={setView} baseKey={key} />
}

function Framed({
  client,
  target,
  object,
  column,
  allObjects,
  view,
  setView,
  baseKey,
}: Props & { target: TargetRef; object: TargetObject; column: TargetColumn; view: 'list' | 'graph'; setView: (v: 'list' | 'graph') => void; baseKey: string }) {
  const [frames, setFrames] = useState<Frame[]>([{ key: baseKey, target, object, column }])
  const frame = frames[frames.length - 1]
  const previous = frames[frames.length - 2]
  const apps = useAsync((signal) => client.projects(signal), 'projects')
  const appOf = (p: string) =>
    (apps.status === 'success' ? apps.data.find((x) => x.project_name === p)?.application : undefined) ?? p

  const track = useCallback(
    async (cont: Continuation, fromLabel: string) => {
      const objects = await client.targets(cont.project)
      const nextObject = objects.find((o) => o.object_id === cont.object_id)
      const columns = nextObject ? await client.columns(cont.project, cont.object_id) : undefined
      const nextColumn = columns?.find((c) => c.column_id === cont.column_id)
      if (!nextObject || !nextColumn) return
      setFrames((fs) => [
        ...fs,
        {
          key: `${cont.project}:${cont.object_id}:${cont.column_id}:${fs.length}`,
          target: { project: cont.project, objectId: cont.object_id, columnId: cont.column_id },
          object: nextObject,
          column: nextColumn,
        },
      ])
      void fromLabel
    },
    [client],
  )
  const leave = useCallback(() => setFrames((fs) => (fs.length > 1 ? fs.slice(0, -1) : fs)), [])
  const callbacks: SessionCallbacks = {
    onTrack: track,
    onLeave: frames.length > 1 ? leave : undefined,
    returnTo: previous ? `${previous.object.object_name}.${previous.column.column_name} (${previous.target.project})` : undefined,
    appName: appOf(frame.target.project),
  }

  return (
    <>
      <div className="view-bar">
        <div className="view-toggle" role="group" aria-label="Walkthrough view">
          <button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}>
            List view
          </button>
          <button type="button" aria-pressed={view === 'graph'} onClick={() => setView('graph')}>
            Graph view
          </button>
        </div>
        <nav className="app-chain" aria-label="Applications">
          {frames.map((f, i) => (
            <span key={f.key} className="app-chain-item">
              {i > 0 && <span aria-hidden="true"> › </span>}
              {i < frames.length - 1 ? (
                <button type="button" onClick={() => setFrames((fs) => fs.slice(0, i + 1))}>
                  {appOf(f.target.project)}
                </button>
              ) : (
                <strong>{appOf(f.target.project)}</strong>
              )}
            </span>
          ))}
        </nav>
      </div>
      {frames.length > 1 && (
        <p className="frame-note" role="note">
          Tracking <strong>{frame.object.object_name}.{frame.column.column_name}</strong> in <strong>{frame.target.project}</strong>
          {previous && <>
            {' '}· started from {previous.object.object_name}.{previous.column.column_name} ({previous.target.project})
          </>}
        </p>
      )}
      {view === 'graph' ? (
        <GraphWalkthrough key={frame.key} client={client} target={frame.target} onTrack={track} onLeave={callbacks.onLeave} returnTo={callbacks.returnTo} appName={callbacks.appName} />
      ) : (
        <Session key={frame.key} client={client} target={frame.target} object={frame.object} column={frame.column} allObjects={allObjects} sessionKey={frame.key} {...callbacks} />
      )}
    </>
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
  onTrack,
  onLeave,
  returnTo,
  appName,
}: Props & { target: TargetRef; object: TargetObject; column: TargetColumn; sessionKey: string } & SessionCallbacks) {
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

  // Where the cards of this level continue in other projects.
  const choices = useMemo(() => (list.status === 'success' ? list.data : []), [list])
  const continuationLookup = useAsync(
    choices.length
      ? async (signal) => {
          const entries = await Promise.all(
            choices.map(
              async (c) =>
                [
                  `${c.source_object_name}.${c.source_column_name}`,
                  await client.continuations(target.project, c.source_object_name, c.source_column_name, signal),
                ] as const,
            ),
          )
          return new Map(entries)
        }
      : null,
    // The key turns over when the list arrives; useAsync only re-runs on a key change.
    `${sessionKey}:cont:${parentKey}:${list.status === 'success' ? 'ready' : 'wait'}`,
  )
  const continuations = continuationLookup.status === 'success' ? continuationLookup.data : undefined

  // Continuations for the ultimate sources panel.
  const sourceList = sources.status === 'success' ? sources.data : []
  const sourceContinuationLookup = useAsync(
    sourceList.length
      ? async (signal) => {
          const entries = await Promise.all(
            sourceList.map(
              async (s) =>
                [`${s.object_name}.${s.column_name}`, await client.continuations(target.project, s.object_name, s.column_name, signal)] as const,
            ),
          )
          return new Map(entries)
        }
      : null,
    `${sessionKey}:srccont:${activeId ?? 'all'}:${sources.status === 'success' ? 'ready' : 'wait'}`,
  )
  const sourceContinuations = sourceContinuationLookup.status === 'success' ? sourceContinuationLookup.data : undefined
  const endpointOf = (c: { source_object_name: string; source_column_name: string }) => `${c.source_object_name}.${c.source_column_name}`
  const targetLabel = `${object.object_name}.${column.column_name}`
  const endpoint = parent ? endpointOf(parent) : targetLabel
  const backLabel = depth === 0 ? null : depth === 1 ? targetLabel : endpointOf(nav.path[depth - 2])
  const allTerminal = list.status === 'success' && list.data.length > 0 && list.data.every((c) => !c.has_more_upstream)
  const goBack = useCallback(() => {
    if (depth === 0) onLeave?.()
    else dispatch({ type: 'back' })
  }, [depth, onLeave])
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
      <TargetPanel project={target.project} appName={appName} object={object} allObjects={allObjects} column={column} />

      <section className="panel choices-panel" aria-label="Upstream choices">
        <div className="walk-bar">
          <div className="panel-head">
            <h2 className="panel-title">Where does this come from?</h2>
            <span className="app-badge">{appName ?? target.project}</span>
            <span className="hop-badge">{stepText}</span>
          </div>
          <p className="walk-instruction" aria-live="polite">
            {instruction}
          </p>
          <div className="walk-controls">
            <button type="button" className="walk-btn" onClick={goBack} disabled={depth === 0 && !onLeave}>
              <span className="walk-btn-main">
                <span aria-hidden="true">‹</span> Back
              </span>
              <span className="walk-btn-sub">{backLabel ? `to ${backLabel}` : onLeave ? `to ${returnTo}` : 'Start of path'}</span>
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
              continuations={continuations}
              onTrack={onTrack}
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
        {sources.status === 'success' && <SourceList sources={sources.data} continuations={sourceContinuations} onTrack={onTrack} />}
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
