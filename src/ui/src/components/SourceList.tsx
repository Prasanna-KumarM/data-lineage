import type { TerminalSource } from '../api/types'
import { RelationBadge } from './Badges'

export function SourceList({ sources }: { sources: TerminalSource[] }) {
  if (sources.length === 0) return <p className="status">No ultimate sources.</p>
  return (
    <ul className="sources">
      {sources.map((source) => (
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
        </li>
      ))}
    </ul>
  )
}
