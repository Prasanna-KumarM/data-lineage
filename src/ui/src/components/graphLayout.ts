import dagre from '@dagrejs/dagre'
import type { ColumnGraph } from '../api/types'

export const NODE_WIDTH = 260
const BASE_HEIGHT = 56
const LINE_HEIGHT = 18
const NAME_CHARS_PER_LINE = 30

export interface PlacedNode {
  id: string
  x: number
  y: number
  width: number
  height: number
}

export function nodeHeight(node: ColumnGraph['nodes'][number]): number {
  const nameLines = Math.ceil(`${node.object_name}.${node.column_name}`.length / NAME_CHARS_PER_LINE)
  const extra = (node.condition ? 1 : 0) + (node.result_expression ? 1 : 0) + Math.max(0, nameLines - 1)
  return BASE_HEIGHT + extra * LINE_HEIGHT
}

/** Left-to-right layers: the target on the left, ultimate sources on the right. Positions are top-left corners. */
export function layoutGraph(graph: ColumnGraph): PlacedNode[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 28, ranksep: 180, marginx: 16, marginy: 16 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const node of graph.nodes) g.setNode(node.node_id, { width: NODE_WIDTH, height: nodeHeight(node) })
  for (const edge of graph.edges) g.setEdge(edge.from_node, edge.to_node)
  dagre.layout(g)
  return graph.nodes.map((node) => {
    const { x, y } = g.node(node.node_id)
    const height = nodeHeight(node)
    return { id: node.node_id, x: x - NODE_WIDTH / 2, y: y - height / 2, width: NODE_WIDTH, height }
  })
}
