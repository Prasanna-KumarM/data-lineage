import { useState } from 'react'
import type { ApiClient } from '../api/client'
import type { TargetObject } from '../api/types'
import { useDebounced } from '../hooks/useDebounced'
import { useAsync } from '../hooks/useAsync'
import { objectLabel } from './objectLabel'
import { ErrorNotice, LoadingNotice } from './Notices'

interface Props {
  client: ApiClient
  project: string
  onChoose: (object: TargetObject) => void
}

/** Search box plus the matching target tables; picking one opens that table's summary. */
export function TableSearch({ client, project, onChoose }: Props) {
  const [text, setText] = useState('')
  const query = useDebounced(text.trim())
  const results = useAsync((signal) => client.searchTargets(project, query, signal), `search:${project}:${query}`)

  return (
    <section className="search" aria-label="Find a target table">
      <label htmlFor="table-search">Search target tables</label>
      <input
        id="table-search"
        type="search"
        placeholder="Type part of a table name"
        value={text}
        autoFocus
        onChange={(event) => setText(event.target.value)}
      />
      {results.status === 'loading' && <LoadingNotice text="Searching…" />}
      {results.status === 'error' && <ErrorNotice error={results.error} onRetry={results.reload} />}
      {results.status === 'success' && (
        <>
          <p className="status" aria-live="polite">
            {results.data.length === 0
              ? 'No target tables match.'
              : `${results.data.length} target ${results.data.length === 1 ? 'table' : 'tables'}`}
          </p>
          <ul className="table-results" aria-label="Target tables">
            {results.data.map((object) => (
              <li key={object.object_id}>
                <button type="button" className="table-result" onClick={() => onChoose(object)}>
                  <span className="table-result-name">{objectLabel(object, results.data)}</span>
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
