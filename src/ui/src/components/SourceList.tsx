import type { Continuation, TerminalSource } from '../api/types'
import { RelationBadge } from './Badges'

interface Props {
  sources: TerminalSource[]
  /** Where a source continues as a target in another project, keyed by OBJECT.COLUMN. */
  continuations?: Map<string, Continuation[]>
  onTrack?: (cont: Continuation, fromLabel: string) => void
  onDetails?: (stepId: string, trigger: HTMLElement) => void
}

export function SourceList({ sources, continuations, onTrack, onDetails }: Props) {
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
            {source.object_type && <span className="card-meta">{source.object_type}</span>}
            {source.leaf_step_id && onDetails && (
              <button
                type="button"
                className="card-details"
                aria-label={`Details for ${endpoint}`}
                onClick={(event) => onDetails(source.leaf_step_id!, event.currentTarget)}
              >
                Details
              </button>
            )}
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
