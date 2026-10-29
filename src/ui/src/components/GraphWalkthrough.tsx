import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { bindProject, type ApiClient } from '../api/client'
import type { ColumnGraph, Continuation, GraphEdge, GraphNode, TargetRef } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { initialWalk, jumpTo, stepBack, stepNext, viewOf, type WalkState } from '../state/graphWalk'
import { RelationBadge } from './Badges'
import { DetailDrawer } from './DetailDrawer'
import { layoutGraph, NODE_WIDTH, nodeHeight } from './graphLayout'
import { ErrorNotice, LoadingNotice } from './Notices'
import { relationStyle } from './relationStyle'
import { KindBadge, hopsText } from './SummaryTable'

type Mode = 'walked' | 'current' | 'next' | 'next-chosen' | 'back' | 'back-chosen' | 'dim'
type WalkData = {
  node: GraphNode
  mode: Mode
  via: GraphEdge | null
  onDetails: () => void
  tracks: Continuation[]
  onTrack: ((cont: Continuation, fromLabel: string) => void) | undefined
} & Record<string, unknown>
type WalkNode = Node<WalkData, 'plain' | 'current'>

const ROLE_LABEL = { target: 'Target', intermediate: 'Intermediate', source: 'Ultimate source' } as const
const label = (n: GraphNode) => `${n.object_name}.${n.column_name}`
const sizeOf = (focus: string) => (n: GraphNode) =>
  n.node_id === focus
    ? { width: 340, height: 190 + (n.condition ? 40 : 0) + (n.result_expression ? 40 : 0) }
    : { width: NODE_WIDTH, height: nodeHeight(n) }

function Handles({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Handle type="target" position={Position.Right} isConnectable={false} />
      {children}
      <Handle type="source" position={Position.Left} isConnectable={false} />
    </>
  )
}

/** A node as drawn on the summary page's graph. */
function PlainView({ data }: NodeProps<WalkNode>) {
  const { node } = data
  return (
    <div className={`graph-node graph-node-${node.role} walk-plain walk-plain-${data.mode}`} data-testid={`walk-node-${data.mode}`}>
      <Handles>
        <div className="graph-node-head">
          <span className="graph-node-role">{ROLE_LABEL[node.role]}</span>
          {node.role === 'source' && node.kind && <KindBadge kind={node.kind} />}
          {node.role !== 'target' && <span className="graph-node-hops">{hopsText(node.hops_min, node.hops_max)}</span>}
        </div>
        <div className="graph-node-name" title={label(node)}>
          {label(node)}
        </div>
        {node.condition && <div className="graph-node-note">when {node.condition}</div>}
        {node.result_expression && <div className="graph-node-note">Value {node.result_expression}</div>}
      </Handles>
    </div>
  )
}

/** The one block shown at standard size, with everything known about the node. */
function Details({ node, via, onDetails, tracks, onTrack }: { node: GraphNode; via: GraphEdge | null; onDetails: () => void; tracks: Continuation[]; onTrack: ((cont: Continuation, fromLabel: string) => void) | undefined }) {
  return (
    <div className="walk-details" data-testid="walk-node-current">
      <div className="graph-node-head">
        <span className="graph-node-role">{ROLE_LABEL[node.role]}</span>
        {node.role === 'source' && node.kind && <KindBadge kind={node.kind} />}
        {node.role !== 'target' && <span className="graph-node-hops">{hopsText(node.hops_min, node.hops_max)}</span>}
      </div>
      <div className="graph-node-name">{label(node)}</div>
      {node.object_type && <div className="walk-current-line">{node.object_type}</div>}
      {via && (
        <div className="walk-current-line">
          <RelationBadge type={via.relation_type} /> {via.component_name ?? 'No component'}
        </div>
      )}
      {node.condition && <div className="walk-current-line">when {node.condition}</div>}
      {node.result_expression && <div className="walk-current-line">Value {node.result_expression}</div>}
      {via && (
        <button type="button" className="walk-current-details nodrag nopan" onClick={onDetails}>
          Full details
        </button>
      )}
      {tracks.map((cont) => (
        <button
          key={cont.project}
          type="button"
          className="card-track nodrag nopan"
          onClick={() => onTrack?.(cont, label(node))}
        >
          Track in {cont.project} →
        </button>
      ))}
    </div>
  )
}

function CurrentView({ data }: NodeProps<WalkNode>) {
  return (
    <div className={`graph-node graph-node-${data.node.role} walk-current`}>
      <Handles>
        <Details node={data.node} via={data.via} onDetails={data.onDetails} tracks={data.tracks} onTrack={data.onTrack} />
      </Handles>
    </div>
  )
}

const nodeTypes = { plain: PlainView, current: CurrentView }

/** Keeps the whole graph in view after every move, as on the summary page. */
function Camera({ trigger }: { trigger: string }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    const timer = setTimeout(() => void fitView({ padding: 0.12, duration: 300 }), 0)
    return () => clearTimeout(timer)
  }, [trigger, fitView])
  return null
}

interface WalkProps {
  client: ApiClient
  target: TargetRef
  onTrack?: (cont: Continuation, fromLabel: string) => void
  onLeave?: () => void
  returnTo?: string
}

export function GraphWalkthrough({ client, target, onTrack, onLeave, returnTo }: WalkProps) {
  const graph = useAsync((signal) => client.columnGraph(target, signal), `walkgraph:${target.project}:${target.objectId}:${target.columnId}`)
  if (graph.status === 'loading' || graph.status === 'idle') return <LoadingNotice text="Loading lineage graph…" />
  if (graph.status === 'error') return <ErrorNotice error={graph.error} onRetry={graph.reload} />
  if (!graph.data.has_lineage) return <p className="status">No lineage found for this column.</p>
  return <Walk graph={graph.data} client={client} target={target} onTrack={onTrack} onLeave={onLeave} returnTo={returnTo} />
}

function Walk({ graph, client, target, onTrack, onLeave, returnTo }: WalkProps & { graph: ColumnGraph }) {
  const [walk, setWalk] = useState<WalkState>(initialWalk)
  const [detailStep, setDetailStep] = useState<string | null>(null)
  const [developer, setDeveloper] = useState(false)
  const bound = useMemo(() => bindProject(client, target.project), [client, target.project])
  const view = viewOf(graph, walk)
  const { current, via, upstream, downstream, nextEdge, backNode } = view
  const nodes = useMemo(() => new Map(graph.nodes.map((n) => [n.node_id, n])), [graph])
  const walkedEdges = useMemo(() => new Map(graph.edges.map((e) => [e.edge_id, e])), [graph])
  const walkedNodes = useMemo(
    () => new Set([view.root.node_id, ...walk.path.map((id) => walkedEdges.get(id)!.to_node)]),
    [walk.path, walkedEdges, view.root.node_id],
  )

  const goNext = useCallback(() => setWalk((w) => stepNext(w, viewOf(graph, w))), [graph])
  const goBack = useCallback(() => {
    if (walk.path.length === 0) {
      onLeave?.()
      return
    }
    setWalk((w) => stepBack(graph, w, viewOf(graph, w)))
  }, [walk.path.length, graph, onLeave])
  const mustPickBack = downstream.length > 1 && via !== null

  // Where the current node continues in other projects.
  const trackLookup = useAsync(
    (signal: AbortSignal) => client.continuations(target.project, current.object_name, current.column_name, signal),
    `cont:${target.project}:${current.node_id}`,
  )
  const tracks = trackLookup.status === 'success' ? trackLookup.data : []

  useEffect(() => setDetailStep(null), [walk.path])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || detailStep) return
      const el = event.target as HTMLElement | null
      if (el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return
      if (event.key === 'ArrowLeft') goBack()
      else if (event.key === 'ArrowRight') goNext()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [detailStep, goBack, goNext])

  const modeOf = (id: string): Mode => {
    if (id === current.node_id) return 'current'
    if (nextEdge?.to_node === id) return 'next-chosen'
    if (upstream.some((e) => e.to_node === id)) return 'next'
    if (backNode?.node_id === id) return 'back-chosen'
    if (mustPickBack && downstream.some((n) => n.node_id === id)) return 'back'
    return walkedNodes.has(id) ? 'walked' : 'dim'
  }

  const flow = useMemo(() => {
    const placed = new Map(layoutGraph(graph, sizeOf(current.node_id)).map((p) => [p.id, p]))
    const flowNodes: WalkNode[] = graph.nodes.map((node) => {
      const p = placed.get(node.node_id)!
      const isCurrent = node.node_id === current.node_id
      return {
        id: node.node_id,
        type: isCurrent ? 'current' : 'plain',
        position: { x: p.x, y: p.y },
        width: p.width,
        height: p.height,
        zIndex: isCurrent ? 10 : 0,
        data: {
          node,
          mode: modeOf(node.node_id),
          via: isCurrent ? via : null,
          onDetails: () => via && setDetailStep(via.step_ids[0] ?? null),
          tracks: isCurrent ? tracks : [],
          onTrack,
        },
        draggable: false,
        connectable: false,
      }
    })
    const flowEdges: Edge[] = graph.edges.map((e) => {
      const walked = walk.path.includes(e.edge_id)
      const candidate = upstream.some((u) => u.edge_id === e.edge_id)
      const chosen = nextEdge?.edge_id === e.edge_id
      const colour = walked ? '#1d4ed8' : candidate ? '#0e7490' : '#64748b'
      return {
        id: e.edge_id,
        source: e.to_node,
        target: e.from_node,
        label: `hop ${e.hop} · ${relationStyle(e.relation_type).label}`,
        labelStyle: { fontSize: 11, fill: '#1f2933' },
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 4,
        labelBgStyle: { fill: '#ffffff', fillOpacity: 0.95, stroke: '#d1d5db' },
        markerEnd: { type: MarkerType.ArrowClosed, color: colour },
        style: { stroke: colour, strokeWidth: walked || chosen ? 3 : candidate ? 2 : 1.4, strokeDasharray: candidate && !chosen ? '6 4' : undefined },
      }
    })
    return { nodes: flowNodes, edges: flowEdges }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, walk, current.node_id, nextEdge, backNode, via, tracks])

  const activate = (id: string) => {
    const mode = modeOf(id)
    if (mode === 'next' || mode === 'next-chosen') {
      const edge = upstream.find((e) => e.to_node === id)
      if (edge) setWalk((w) => ({ ...w, nextId: edge.edge_id }))
    } else if (mode === 'back' || mode === 'back-chosen') {
      setWalk((w) => ({ ...w, backId: id }))
    } else if (mode === 'walked') {
      const index = walk.path.findIndex((edgeId) => walkedEdges.get(edgeId)?.to_node === id)
      setWalk((w) => jumpTo(w, index + 1))
    }
  }

  const pathNodes = walk.path.map((id) => nodes.get(walkedEdges.get(id)!.to_node)!)
  const instruction = (() => {
    if (upstream.length === 0) return via ? 'You have reached an ultimate source. Press Back to try another branch.' : 'Nothing further upstream.'
    if (upstream.length > 1 && !nextEdge) return `This splits into ${upstream.length} mappings. Pick the one to follow, then press Next.`
    return `Press Next to see where ${label(nodes.get(nextEdge!.to_node)!)} comes from.`
  })()
  const backInstruction = mustPickBack && !backNode ? `This column is reached from ${downstream.length} places. Pick where to go back to.` : null

  return (
    <section className="panel graph-walk" aria-label="Graph walkthrough">
      <div className="walk-bar graph-walk-bar">
        <div className="panel-head">
          <h2 className="panel-title">Where does this come from?</h2>
          <span className="app-badge">{target.project}</span>
          <span className="hop-badge">Step {walk.path.length + 1}</span>
        </div>
        <p className="walk-instruction" aria-live="polite">
          {instruction} {backInstruction}
        </p>
        <div className="walk-controls">
          <button type="button" className="walk-btn" onClick={goBack} disabled={!backNode && !onLeave}>
            <span className="walk-btn-main">
              <span aria-hidden="true">‹</span> Back
            </span>
            <span className="walk-btn-sub">{backNode ? `to ${label(backNode)}` : via ? 'Pick where to go back to' : onLeave ? `to ${returnTo}` : 'Start of path'}</span>
          </button>
          <ol className="graph-walk-path" aria-label="Your path">
            <li>
              <button type="button" onClick={() => setWalk((w) => jumpTo(w, 0))} disabled={walk.path.length === 0}>
                {label(view.root)}
              </button>
            </li>
            {pathNodes.map((n, i) => (
              <li key={`${n.node_id}:${i}`}>
                <button type="button" onClick={() => setWalk((w) => jumpTo(w, i + 1))} disabled={i === pathNodes.length - 1}>
                  {label(n)}
                </button>
              </li>
            ))}
          </ol>
          <button type="button" className="walk-btn primary" onClick={goNext} disabled={!nextEdge}>
            <span className="walk-btn-main">
              Next <span aria-hidden="true">›</span>
            </span>
            <span className="walk-btn-sub">
              {nextEdge ? `Go into ${label(nodes.get(nextEdge.to_node)!)}` : upstream.length ? 'Pick a mapping first' : 'Nothing further upstream'}
            </span>
          </button>
        </div>
      </div>

      <div className="graph-canvas graph-walk-canvas" data-testid="walk-canvas">
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3, maxZoom: 1.1 }}
          minZoom={0.1}
          maxZoom={1.5}
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          onNodeClick={(_, clicked) => activate(clicked.id)}
        >
          <Background gap={20} />
          <Controls showInteractive={false} showFitView={false} />
          <Camera trigger={current.node_id} />
          <Panel position="top-right">
            <FitAll focusId={current.node_id} />
          </Panel>
        </ReactFlow>
      </div>

      {upstream.length > 1 && (
        <div className="block">
          <h3 className="block-title">Pick one to follow</h3>
          <ul className="cards" aria-label="Upstream mappings">
            {upstream.map((e) => {
              const n = nodes.get(e.to_node)!
              const chosen = nextEdge?.edge_id === e.edge_id
              return (
                <li key={e.edge_id} className="card-item">
                  <button
                    type="button"
                    className={`card tone-${relationStyle(e.relation_type).tone}${chosen ? ' selected' : ''}`}
                    aria-pressed={chosen}
                    onClick={() => setWalk((w) => ({ ...w, nextId: chosen ? null : e.edge_id }))}
                  >
                    <span className="card-title">{label(n)}</span>
                    <span className="card-badges">
                      <RelationBadge type={e.relation_type} />
                    </span>
                    {(e.condition || e.result_expression) && (
                      <span className="card-expr">
                        {e.condition && (
                          <span className="expr-line">
                            <span className="expr-tag when">When</span>
                            <code>{e.condition}</code>
                          </span>
                        )}
                        {e.result_expression && (
                          <span className="expr-line">
                            <span className="expr-tag value">Value</span>
                            <code>{e.result_expression}</code>
                          </span>
                        )}
                      </span>
                    )}
                    <span className="card-meta">{e.component_name ?? 'No component'}</span>
                    <span className="card-meta">{n.role === 'source' ? 'Ultimate source' : 'Continues upstream'}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {mustPickBack && (
        <div className="block">
          <h3 className="block-title">Go back to</h3>
          <ul className="cards" aria-label="Previous steps">
            {downstream.map((n) => (
              <li key={n.node_id} className="card-item">
                <button
                  type="button"
                  className={`card${backNode?.node_id === n.node_id ? ' selected' : ''}`}
                  aria-pressed={backNode?.node_id === n.node_id}
                  onClick={() => setWalk((w) => ({ ...w, backId: n.node_id }))}
                >
                  <span className="card-title">{label(n)}</span>
                  {walkedNodes.has(n.node_id) && <span className="card-meta">On your path</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {detailStep && (
        <DetailDrawer client={bound} stepId={detailStep} developer={developer} onDeveloperChange={setDeveloper} onClose={() => setDetailStep(null)} />
      )}
    </section>
  )
}

function FitAll({ focusId }: { focusId: string }) {
  const { fitView } = useReactFlow()
  return (
    <div className="graph-walk-zoom">
      <button type="button" className="graph-fit" onClick={() => void fitView({ nodes: [{ id: focusId }], padding: 0.6, maxZoom: 1.2, duration: 250 })}>
        Zoom to current
      </button>
      <button type="button" className="graph-fit" onClick={() => void fitView({ padding: 0.12, duration: 250 })}>
        Fit to screen
      </button>
    </div>
  )
}
