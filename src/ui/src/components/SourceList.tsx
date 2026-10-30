import type { Continuation, TerminalSource } from '../api/types'
import { RelationBadge } from './Badges'

interface Props {
  sources: TerminalSource[]
  /** Where a source continues as a target in another project, keyed by OBJECT.COLUMN. */
  continuations?: Map<string, Continuation[]>
  onTrack?: (cont: Continuation, fromLabel: string) => void
}

export function SourceList({ sources, continuations, onTrack }: Props) {
  if (sources.length === 0) return <p className="status">No ultimate sources.</p>
  return (
    <ul className="sources">
      {sources.map((source) => {
        const endpoint = `${source.object_name}.${source.column_name}`
        return (
          <li key={source.terminal_id} className="source">
            <span className="source-name">
              {source.object_name}.{source.column_name}
            </span>
            <span className="card-badges">
              {source.leaf_relation_types.map((type) => (
                <RelationBadge key={type} type={type} />
              ))}
            </span>
            {source.condition && <span className="source-condition">when {source.condition}</span>}
            {source.object_type && <span className="card-meta">{source.object_type}</span>}
            {continuations?.get(endpoint)?.map((cont) => (
              <button key={cont.project} type="button" className="source-track" onClick={() => onTrack?.(cont, endpoint)}>
                Continue in {cont.project} →
              </button>
            ))}
          </li>
        )
      })}
    </ul>
  )
}
