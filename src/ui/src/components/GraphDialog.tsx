import { useEffect, useRef } from 'react'
import type { ApiClient } from '../api/client'
import type { TargetRef } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { ErrorNotice, LoadingNotice } from './Notices'
import { LineageGraph } from './LineageGraph'

interface Props {
  client: ApiClient
  target: TargetRef
  tableName: string
  columnName: string
  onClose: () => void
}

/** Modal window with the whole lineage graph of one target column. */
export function GraphDialog({ client, target, tableName, columnName, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const graph = useAsync(
    (signal) => client.columnGraph(target, signal),
    `graph:${target.project}:${target.objectId}:${target.columnId}`,
  )

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      opener?.focus?.()
    }
  }, [onClose])

  const totals = graph.status === 'success' ? graph.data.totals : null

  return (
    <div className="graph-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="graph-dialog" role="dialog" aria-modal="true" aria-label={`Lineage graph of ${columnName}`}>
        <header className="graph-dialog-head">
          <div>
            <h2>
              {tableName}.{columnName}
            </h2>
            {totals && (
              <p className="card-meta">
                {totals.sources} {totals.sources === 1 ? 'ultimate source' : 'ultimate sources'} · up to {totals.hops_max}{' '}
                {totals.hops_max === 1 ? 'hop' : 'hops'} · {totals.edges} {totals.edges === 1 ? 'mapping' : 'mappings'}
              </p>
            )}
          </div>
          <button type="button" ref={closeRef} className="graph-close" onClick={onClose}>
            Close
          </button>
        </header>
        {graph.status === 'loading' && <LoadingNotice text="Loading lineage graph…" />}
        {graph.status === 'error' && <ErrorNotice error={graph.error} onRetry={graph.reload} />}
        {graph.status === 'success' &&
          (graph.data.has_lineage ? <LineageGraph graph={graph.data} /> : <p className="status">No lineage found for this column.</p>)}
      </div>
    </div>
  )
}
