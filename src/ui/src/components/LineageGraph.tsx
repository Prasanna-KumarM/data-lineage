import { useMemo, useState } from 'react'
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
import type { ColumnGraph, GraphEdge, GraphNode } from '../api/types'
import { layoutGraph } from './graphLayout'
import { relationStyle } from './relationStyle'
import { KindBadge, hopsText } from './SummaryTable'

type LineageNodeData = { node: GraphNode } & Record<string, unknown>
type LineageNode = Node<LineageNodeData, 'lineage'>

const ROLE_LABEL = { target: 'Target', intermediate: 'Intermediate', source: 'Ultimate source' } as const

function LineageNodeView({ data }: NodeProps<LineageNode>) {
  const { node } = data
  return (
    <div className={`graph-node graph-node-${node.role}`} data-testid={`graph-node-${node.role}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="graph-node-head">
        <span className="graph-node-role">{ROLE_LABEL[node.role]}</span>
        {node.role === 'source' && node.kind && <KindBadge kind={node.kind} />}
        {node.role !== 'target' && <span className="graph-node-hops">{hopsText(node.hops_min, node.hops_max)}</span>}
      </div>
      <div className="graph-node-name" title={`${node.object_name}.${node.column_name}`}>
        {node.object_name}.{node.column_name}
      </div>
      {node.condition && <div className="graph-node-note">when {node.condition}</div>}
      {node.result_expression && <div className="graph-node-note">Value {node.result_expression}</div>}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}

const nodeTypes = { lineage: LineageNodeView }

function toFlow(graph: ColumnGraph, selectedEdge: string | null): { nodes: LineageNode[]; edges: Edge[] } {
  const placed = new Map(layoutGraph(graph).map((p) => [p.id, p]))
  const byId = new Map(graph.nodes.map((n) => [n.node_id, n]))
  const nodes: LineageNode[] = graph.nodes.map((node) => {
    const p = placed.get(node.node_id)!
    return {
      id: node.node_id,
      type: 'lineage',
      position: { x: p.x, y: p.y },
      width: p.width,
      height: p.height,
      data: { node },
      draggable: false,
      connectable: false,
    }
  })
  const edges: Edge[] = graph.edges.map((e) => {
    const intoSource = byId.get(e.to_node)?.role === 'source'
    const colour = intoSource ? '#0e7490' : '#64748b'
    return {
      id: e.edge_id,
      source: e.from_node,
      target: e.to_node,
      label: `hop ${e.hop} · ${relationStyle(e.relation_type).label}`,
      labelStyle: { fontSize: 11, fill: '#1f2933' },
      labelBgPadding: [6, 3],
      labelBgBorderRadius: 4,
      labelBgStyle: { fill: '#ffffff', fillOpacity: 0.95, stroke: '#d1d5db' },
      markerEnd: { type: MarkerType.ArrowClosed, color: colour },
      style: { stroke: colour, strokeWidth: selectedEdge === e.edge_id ? 3 : 1.6 },
      selected: selectedEdge === e.edge_id,
      ariaLabel: `Mapping at hop ${e.hop}`,
    }
  })
  return { nodes, edges }
}

function FitButton() {
  const { fitView } = useReactFlow()
  return (
    <button type="button" className="graph-fit" onClick={() => void fitView({ padding: 0.15, duration: 250 })}>
      Fit to screen
    </button>
  )
}

function EdgeDetail({ edge, graph }: { edge: GraphEdge; graph: ColumnGraph }) {
  const name = (id: string) => {
    const n = graph.nodes.find((x) => x.node_id === id)
    return n ? `${n.object_name}.${n.column_name}` : id
  }
  return (
    <div className="graph-edge-detail" aria-label="Selected mapping">
      <strong>
        {name(edge.from_node)} ← {name(edge.to_node)}
      </strong>
      <span>
        hop {edge.hop} · {relationStyle(edge.relation_type).label}
        {edge.component_name ? ` · ${edge.component_name}` : ''}
      </span>
      {edge.condition && <span>when {edge.condition}</span>}
      {edge.result_expression && <span>Value {edge.result_expression}</span>}
    </div>
  )
}

export function LineageGraph({ graph }: { graph: ColumnGraph }) {
  const [selected, setSelected] = useState<string | null>(null)
  const flow = useMemo(() => toFlow(graph, selected), [graph, selected])
  const selectedEdge = graph.edges.find((e) => e.edge_id === selected) ?? null

  return (
    <div className="graph-wrap">
      <div className="graph-canvas" data-testid="graph-canvas">
        <ReactFlow
          nodes={flow.nodes}
          edges={flow.edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.1}
          maxZoom={1.5}
          nodesDraggable={false}
          nodesConnectable={false}
          proOptions={{ hideAttribution: true }}
          onEdgeClick={(_, edge) => setSelected((cur) => (cur === edge.id ? null : edge.id))}
          onPaneClick={() => setSelected(null)}
        >
          <Background gap={20} />
          <Controls showInteractive={false} showFitView={false} />
          <Panel position="top-right">
            <FitButton />
          </Panel>
          {selectedEdge && (
            <Panel position="bottom-center">
              <EdgeDetail edge={selectedEdge} graph={graph} />
            </Panel>
          )}
        </ReactFlow>
      </div>
      <p className="graph-legend">
        <span className="legend-swatch legend-target" /> Target
        <span className="legend-swatch legend-intermediate" /> Intermediate
        <span className="legend-swatch legend-source" /> Ultimate source
        <span className="card-meta">Arrows point from the target towards its ultimate sources. Click a line for its mapping.</span>
      </p>
    </div>
  )
}
