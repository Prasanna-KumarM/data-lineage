import { useMemo, useState } from 'react'
import type { ApiClient } from '../api/client'
import type { Project, TargetObject } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { useDebounced } from '../hooks/useDebounced'
import { objectLabel } from './objectLabel'
import { ErrorNotice, LoadingNotice } from './Notices'

interface Props {
  client: ApiClient
  /** All cataloged projects, including ones whose database is missing (they still fill the filter dropdowns). */
  entries: Project[]
  onChoose: (object: TargetObject, project: string) => void
}

export const catalogSubtitle = (p: Project) => [p.value_chain, p.source_system, p.project_name].filter(Boolean).join(' · ')

/** Business landing: only the cataloged (e.g. GFRS-bound) tables, browsable by value chain and target system. */
export function BusinessSearch({ client, entries, onChoose }: Props) {
  const [text, setText] = useState('')
  const [chain, setChain] = useState('')
  const [targetSystem, setTargetSystem] = useState('')
  const query = useDebounced(text.trim())

  const chains = useMemo(
    () => [...new Set(entries.map((p) => p.value_chain).filter((v): v is string => Boolean(v)))].sort(),
    [entries],
  )
  const systems = useMemo(
    () => [...new Set(entries.map((p) => p.target_system).filter((v): v is string => Boolean(v)))].sort(),
    [entries],
  )

  const visible = entries.filter(
    (p) => (!chain || p.value_chain === chain) && (!targetSystem || p.target_system === targetSystem),
  )
  // Tables can only be read from projects whose database is up.
  const fetchable = visible.filter((p) => p.ready !== false && p.startable !== false)
  const visibleKey = fetchable.map((p) => p.project_name).sort().join(',')
  const tables = useAsync(
    fetchable.length
      ? async (signal) => {
          const grouped = await Promise.all(
            fetchable.map(async (p) => {
              const wanted = new Set(p.business_tables ?? [])
              const targets = await client.targets(p.project_name, signal)
              return targets.filter((t) => wanted.has(t.object_name)).map((object) => ({ object, project: p }))
            }),
          )
          return grouped.flat()
        }
      : null,
    `biztables:${visibleKey}`,
  )

  const needle = query.toLowerCase()
  const rows = (tables.status === 'success' ? tables.data : []).filter(
    (r) => !needle || r.object.object_name.toLowerCase().includes(needle),
  )
  const allObjects = rows.map((r) => r.object)

  return (
    <section className="search" aria-label="Find a target table">
      <div className="business-filters">
        <label>
          Value chain
          <select value={chain} onChange={(e) => setChain(e.target.value)}>
            <option value="">All value chains</option>
            {chains.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          Target system
          <select value={targetSystem} onChange={(e) => setTargetSystem(e.target.value)}>
            <option value="">All target systems</option>
            {systems.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Search target tables
          <input
            type="search"
            placeholder="Type part of a table name"
            value={text}
            autoFocus
            onChange={(e) => setText(e.target.value)}
          />
        </label>
      </div>
      {tables.status === 'loading' && <LoadingNotice text="Loading tables…" />}
      {tables.status === 'error' && <ErrorNotice error={tables.error} onRetry={tables.reload} />}
      {(tables.status === 'success' || tables.status === 'idle') && (
        <>
          <p className="status" aria-live="polite">
            {rows.length === 0
              ? 'No target tables match.'
              : `${rows.length} target ${rows.length === 1 ? 'table' : 'tables'}`}
          </p>
          <ul className="table-results" aria-label="Target tables">
            {rows.map(({ object, project }) => (
              <li key={`${project.project_name}/${object.object_id}`}>
                <button type="button" className="table-result" onClick={() => onChoose(object, project.project_name)}>
                  <span className="table-result-name">{objectLabel(object, allObjects)}</span>
                  <span className="table-result-sub">{catalogSubtitle(project)}</span>
                  <span className="card-meta">
                    {object.column_count} {object.column_count === 1 ? 'column' : 'columns'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
