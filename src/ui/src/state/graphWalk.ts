import type { ColumnGraph, GraphEdge, GraphNode } from '../api/types'

/** Edges run from the node nearer the target (`from_node`) to the node nearer the sources (`to_node`). */
export interface WalkState {
  /** Edge ids walked from the target, in order. */
  path: string[]
  /** Chosen upstream edge when the current node splits. */
  nextId: string | null
  /** Chosen downstream node when the current node is reached from several places. */
  backId: string | null
}

export const initialWalk: WalkState = { path: [], nextId: null, backId: null }

export interface WalkView {
  root: GraphNode
  current: GraphNode
  /** Edge that was walked into the current node. */
  via: GraphEdge | null
  upstream: GraphEdge[]
  /** Distinct nodes one step closer to the target. */
  downstream: GraphNode[]
  nextEdge: GraphEdge | null
  backNode: GraphNode | null
}

export function viewOf(graph: ColumnGraph, walk: WalkState): WalkView {
  const nodes = new Map(graph.nodes.map((n) => [n.node_id, n]))
  const edges = new Map(graph.edges.map((e) => [e.edge_id, e]))
  const root = graph.nodes.find((n) => n.role === 'target') ?? graph.nodes[0]
  const via = walk.path.length ? edges.get(walk.path[walk.path.length - 1]) ?? null : null
  const current = via ? nodes.get(via.to_node) ?? root : root
  const upstream = graph.edges.filter((e) => e.from_node === current.node_id)
  const downstream = [...new Set(graph.edges.filter((e) => e.to_node === current.node_id).map((e) => e.from_node))]
    .map((id) => nodes.get(id))
    .filter((n): n is GraphNode => Boolean(n))
  const nextEdge = upstream.length === 1 ? upstream[0] : upstream.find((e) => e.edge_id === walk.nextId) ?? null
  const backNode = !via ? null : downstream.length === 1 ? downstream[0] : downstream.find((n) => n.node_id === walk.backId) ?? null
  return { root, current, via, upstream, downstream, nextEdge, backNode }
}

/** Shortest list of edges from the target to a node. */
export function pathTo(graph: ColumnGraph, nodeId: string): string[] {
  const root = graph.nodes.find((n) => n.role === 'target')
  if (!root || root.node_id === nodeId) return []
  const reached = new Map<string, string[]>([[root.node_id, []]])
  const queue = [root.node_id]
  while (queue.length) {
    const id = queue.shift()!
    for (const e of graph.edges) {
      if (e.from_node !== id || reached.has(e.to_node)) continue
      reached.set(e.to_node, [...reached.get(id)!, e.edge_id])
      if (e.to_node === nodeId) return reached.get(nodeId)!
      queue.push(e.to_node)
    }
  }
  return []
}

export function stepNext(walk: WalkState, view: WalkView): WalkState {
  return view.nextEdge ? { path: [...walk.path, view.nextEdge.edge_id], nextId: null, backId: null } : walk
}

export function stepBack(graph: ColumnGraph, walk: WalkState, view: WalkView): WalkState {
  if (!view.backNode || !view.via) return walk
  const path = view.via.from_node === view.backNode.node_id ? walk.path.slice(0, -1) : pathTo(graph, view.backNode.node_id)
  return { path, nextId: null, backId: null }
}

export function jumpTo(walk: WalkState, length: number): WalkState {
  return { path: walk.path.slice(0, length), nextId: null, backId: null }
}
