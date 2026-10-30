export interface Project {
  project_name: string
  folder?: string
  /** Only present (false) when the project's database exists but cannot be used yet. */
  ready?: boolean
  problem?: string
  /** Only present (false) when the project is reachable only through continuation. */
  startable?: boolean
  /** Application name shown instead of the project code, when configured. */
  application?: string
}

export interface BusinessProcess {
  business_process_id: string | null
  business_process_name: string | null
}

export interface TargetObject {
  object_id: string
  object_name: string
  source_project: string | null
  business_processes: BusinessProcess[]
  column_count: number
}

export interface TargetColumn {
  column_id: string
  column_name: string
  step_count: number
}

export interface Choice {
  step_id: string
  relation_id: string
  relation_type: string
  source_object_id: string
  source_column_id: string
  source_object_name: string
  source_column_name: string
  target_object_id: string
  target_column_id: string
  target_object_name: string
  target_column_name: string
  component_id: string | null
  component_name: string | null
  component_type: string | null
  business_process_id: string | null
  business_process_name: string | null
  confidence_class: string | null
  confidence_reason_code: string | null
  traversal_path: string | null
  driving_expression: string | null
  result_expression: string | null
  expression_id: string | null
  lineage_level: number
  is_terminal: boolean
  has_more_upstream: boolean
  upstream_choice_count: number
  /** Mappings sharing this path; present from the contributors table. */
  contributor_count?: number
  /** Component names of those mappings, sorted. */
  contributor_components?: string[]
}

export interface TerminalSource {
  terminal_id: string
  object_id: string
  column_id: string
  object_name: string
  column_name: string
  object_type: string | null
  condition: string | null
  result_expression: string | null
  leaf_relation_types: string[]
}

export interface Continuation {
  /** Project whose database tracks this endpoint as a target column. */
  project: string
  object_id: string
  column_id: string
}

export interface TargetRef {
  project: string
  objectId: string
  columnId: string
}

export interface UpstreamResponse {
  choices: Choice[]
}

export interface UltimateSourcesResponse {
  project: string
  object_id: string
  column_id: string
  step_id: string | null
  terminal_sources: TerminalSource[]
}

export interface RemainingDepth {
  step_id: string
  is_terminal: boolean
  remaining_hops_exact: number | null
  remaining_hops_min: number
  remaining_hops_max: number
}

export interface Endpoint {
  object_id: string | null
  object_name: string | null
  object_type: string | null
  column_id: string | null
  column_name: string | null
}

export interface Dependency {
  operand_order: number | null
  object_id: string | null
  column_id: string | null
  object_name: string | null
  object_type: string | null
  column_name: string | null
}

export interface StepDetail {
  step_id: string
  path_id: string
  lineage_level: number
  hop_count: number | null
  relation_id: string
  relation_type: string
  source: Endpoint
  target: Endpoint
  component: { component_id: string | null; component_name: string | null; component_type: string | null }
  business_process: BusinessProcess
  confidence: { confidence_class: string | null; reason_code: string | null; reason: string | null }
  traversal_path: string | null
  expression_id: string | null
  driving_expression: string | null
  result_expression: string | null
  dependencies: Dependency[]
  persistence: { status: string; reason_code: string | null; reason: string | null } | null
  step_ids: string[]
  contributors?: Contributor[]
}

export interface Contributor {
  relation_id: string
  relation_type: string
  driving_expression: string | null
  result_expression: string | null
  component_id: string | null
  component_name: string | null
  component_type: string | null
  business_process_name: string | null
}

export type SourceKind = 'column' | 'constant' | 'function' | 'not_persisted'

export interface RouteStep {
  endpoint: string
  relation_type: string
  component_name: string | null
}

export interface SummarySource {
  terminal_id: string
  object_name: string
  column_name: string
  object_type: string | null
  kind: SourceKind
  condition: string | null
  result_expression: string | null
  leaf_relation_types: string[]
  hops_min: number
  hops_max: number
  route_count: number
  route: RouteStep[]
}

export interface SummaryFlags {
  constant: boolean
  function: boolean
  not_persisted: boolean
  case_branches: boolean
  inferred: boolean
}

export interface SummaryColumn {
  column_id: string
  column_name: string
  has_lineage: boolean
  source_count: number
  hops_min: number | null
  hops_max: number | null
  flags: SummaryFlags
  sources: SummarySource[]
}

export interface TableSummary {
  object: TargetObject
  totals: { columns: number; with_lineage: number }
  columns: SummaryColumn[]
}

export interface GraphNode {
  node_id: string
  role: 'target' | 'intermediate' | 'source'
  object_name: string
  column_name: string
  object_type: string | null
  kind: SourceKind | null
  condition: string | null
  result_expression: string | null
  hops_min: number
  hops_max: number
}

export interface GraphEdge {
  edge_id: string
  from_node: string
  to_node: string
  relation_id: string
  step_ids: string[]
  relation_type: string
  component_name: string | null
  condition: string | null
  result_expression: string | null
  hop: number
}

export interface ColumnGraph {
  project: string
  object_id: string
  column_id: string
  has_lineage: boolean
  nodes: GraphNode[]
  edges: GraphEdge[]
  totals: { nodes: number; edges: number; sources: number; hops_max: number }
}
