import { useMemo, useState } from 'react'
import type { SourceKind, SummaryColumn, SummarySource, TableSummary } from '../api/types'
import { relationStyle } from './relationStyle'

type SortKey = 'name' | 'hops' | 'sources'

const KIND_LABEL: Record<SourceKind, string> = {
  column: 'Column',
  constant: 'Constant',
  function: 'Function',
  not_persisted: 'Not persisted',
}

const FLAGS: { key: keyof SummaryColumn['flags']; label: string; title: string }[] = [
  { key: 'constant', label: 'Constant', title: 'A source is a constant' },
  { key: 'function', label: 'Function', title: 'A source is a runtime function' },
  { key: 'not_persisted', label: 'Not persisted', title: 'The target attribute is not persisted' },
  { key: 'case_branches', label: 'CASE', title: 'The value depends on conditions' },
  { key: 'inferred', label: 'Inferred', title: 'Some mappings on the way are inferred, not explicit' },
]

const hops = (n: number) => `${n} ${n === 1 ? 'hop' : 'hops'}`
export const hopsText = (min: number, max: number) => (min === max ? hops(min) : `${min}–${max} hops`)
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export function KindBadge({ kind }: { kind: SourceKind }) {
  return <span className={`badge kind-${kind}`}>{KIND_LABEL[kind]}</span>
}

function PathLine({ column, source }: { column: string; source: SummarySource }) {
  const nodes = [column, ...source.route.map((s) => s.endpoint)]
  return (
    <li className="path-line">
      <span className="hops-badge">{hopsText(source.hops_min, source.hops_max)}</span>
      <span className="route">
        {nodes.map((node, index) => (
          <span key={index} className="route-part">
            {index > 0 && (
              <span className="route-arrow" aria-hidden="true">
                {' ← '}
              </span>
            )}
            <span
              className={
                index === 0 ? 'route-node route-target' : index === nodes.length - 1 ? 'route-node route-source' : 'route-node'
              }
              title={
                index > 0
                  ? `${relationStyle(source.route[index - 1].relation_type).label}${
                      source.route[index - 1].component_name ? ` · ${source.route[index - 1].component_name}` : ''
                    }`
                  : undefined
              }
            >
              {node}
            </span>
          </span>
        ))}
      </span>
      {source.route_count > 1 && <span className="card-meta">{plural(source.route_count, 'route', 'routes')}</span>}
    </li>
  )
}

function SourceLine({ source, onOpenDetail }: { source: SummarySource; onOpenDetail?: (stepId: string, trigger: HTMLElement) => void }) {
  return (
    <li className="source-line">
      <span className="source-name">
        {source.object_name}.{source.column_name}
      </span>
      <KindBadge kind={source.kind} />
      {(source.condition || source.result_expression) && (
        <span className="card-expr">
          {source.condition && (
            <span className="expr-line">
              <span className="expr-tag when">EXPR</span>
              <code>{source.condition}</code>
            </span>
          )}
          {source.result_expression && (
            <span className="expr-line">
              <span className="expr-tag value">OUTPUT</span>
              <code>{source.result_expression}</code>
            </span>
          )}
        </span>
      )}
      {source.leaf_step_id && onOpenDetail && (
        <button
          type="button"
          className="card-details"
          aria-label={`Details for ${source.object_name}.${source.column_name}`}
          onClick={(event) => onOpenDetail(source.leaf_step_id!, event.currentTarget)}
        >
          Details
        </button>
      )}
    </li>
  )
}

function Disclosure({
  expanded,
  onToggle,
  label,
  children,
}: {
  expanded: boolean
  onToggle: () => void
  label: string
  children: React.ReactNode
}) {
  return (
    <button type="button" className="disclosure" aria-expanded={expanded} aria-label={label} onClick={onToggle}>
      <span aria-hidden="true">{expanded ? '▾' : '▸'}</span> {children}
    </button>
  )
}

function sortColumns(columns: SummaryColumn[], key: SortKey): SummaryColumn[] {
  if (key === 'name') return columns
  const value = (c: SummaryColumn) => (key === 'hops' ? c.hops_max : c.source_count) ?? -1
  return [...columns].sort((a, b) => value(b) - value(a) || a.column_name.localeCompare(b.column_name))
}

interface Props {
  summary: TableSummary
  onOpenColumn: (column: SummaryColumn) => void
  onOpenGraph: (column: SummaryColumn) => void
  onOpenDetail?: (stepId: string, trigger: HTMLElement) => void
}

export function SummaryTable({ summary, onOpenColumn, onOpenGraph, onOpenDetail }: Props) {
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState<SortKey>('name')
  const [openPaths, setOpenPaths] = useState<Set<string>>(new Set())
  const [openSources, setOpenSources] = useState<Set<string>>(
    () => new Set(summary.columns.filter((c) => c.has_lineage).map((c) => c.column_id)),
  )

  const needle = filter.trim().toLowerCase()
  const rows = useMemo(
    () =>
      sortColumns(
        summary.columns.filter((c) => !needle || c.column_name.toLowerCase().includes(needle)),
        sort,
      ),
    [summary.columns, needle, sort],
  )

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set)
    if (!next.delete(id)) next.add(id)
    setter(next)
  }
  const withLineage = summary.columns.filter((c) => c.has_lineage).map((c) => c.column_id)

  return (
    <section className="summary" aria-label="Table summary">
      <div className="summary-toolbar">
        <label>
          <span className="toolbar-label">Filter columns</span>
          <input type="search" value={filter} placeholder="Column name" onChange={(e) => setFilter(e.target.value)} />
        </label>
        <label>
          <span className="toolbar-label">Sort by</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            <option value="name">Column name</option>
            <option value="hops">Most hops</option>
            <option value="sources">Most sources</option>
          </select>
        </label>
        <div className="toolbar-buttons">
          <button
            type="button"
            onClick={() => {
              setOpenPaths(new Set(withLineage))
              setOpenSources(new Set(withLineage))
            }}
          >
            Expand all
          </button>
          <button
            type="button"
            onClick={() => {
              setOpenPaths(new Set())
              setOpenSources(new Set())
            }}
          >
            Collapse all
          </button>
        </div>
        <p className="status" aria-live="polite">
          Showing {rows.length} of {summary.columns.length} columns
        </p>
      </div>

      <table className="summary-table">
        <caption className="visually-hidden">Columns of {summary.object.object_name}</caption>
        <thead>
          <tr>
            <th scope="col">Column</th>
            <th scope="col">Paths</th>
            <th scope="col">Ultimate sources</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((column) => (
            <tr key={column.column_id}>
              <th scope="row" className="column-cell">
                <button type="button" className="link" onClick={() => onOpenColumn(column)}>
                  {column.column_name}
                </button>
                {column.has_lineage && (
                  <button
                    type="button"
                    className="graph-open"
                    aria-label={`Graph of ${column.column_name}`}
                    title="Show the lineage graph"
                    onClick={() => onOpenGraph(column)}
                  >
                    <span aria-hidden="true">⦿</span> Graph
                  </button>
                )}
                <span className="card-badges">
                  {!column.has_lineage && <span className="badge muted">No lineage</span>}
                  {FLAGS.filter((f) => column.flags[f.key]).map((f) => (
                    <span key={f.key} className="badge flag" title={f.title}>
                      {f.label}
                    </span>
                  ))}
                </span>
              </th>
              <td>
                {!column.has_lineage ? (
                  <span className="muted">No lineage found</span>
                ) : (
                  <>
                    <Disclosure
                      expanded={openPaths.has(column.column_id)}
                      onToggle={() => toggle(openPaths, setOpenPaths, column.column_id)}
                      label={`Paths of ${column.column_name}`}
                    >
                      {plural(column.source_count, 'path', 'paths')} · {hopsText(column.hops_min!, column.hops_max!)}
                    </Disclosure>
                    {openPaths.has(column.column_id) && (
                      <ul className="path-list" aria-label={`Paths of ${column.column_name}`}>
                        {column.sources.map((source) => (
                          <PathLine key={source.terminal_id} column={column.column_name} source={source} />
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </td>
              <td>
                {!column.has_lineage ? (
                  <span className="muted">No sources</span>
                ) : (
                  <>
                    <Disclosure
                      expanded={openSources.has(column.column_id)}
                      onToggle={() => toggle(openSources, setOpenSources, column.column_id)}
                      label={`Ultimate sources of ${column.column_name}`}
                    >
                      {plural(column.source_count, 'source', 'sources')}
                    </Disclosure>
                    {openSources.has(column.column_id) && (
                      <ul className="source-list" aria-label={`Ultimate sources of ${column.column_name}`}>
                        {column.sources.map((source) => (
                          <SourceLine key={source.terminal_id} source={source} onOpenDetail={onOpenDetail} />
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={3} className="muted">
                No column matches the filter.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
