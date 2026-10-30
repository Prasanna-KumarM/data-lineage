import type { Choice, Continuation } from '../api/types'
import { ConfidenceBadge, RelationBadge } from './Badges'
import { relationStyle } from './relationStyle'

interface Props {
  choices: Choice[]
  selectedStepId: string | null
  /** Step whose detail drawer is open, if any. */
  detailStepId: string | null
  /** True for the target's own choices, where "no intermediate steps" is accurate. */
  atRoot: boolean
  /** Continuations of terminal choices into other projects, keyed by OBJECT.COLUMN. */
  continuations?: Map<string, Continuation[]>
  onTrack?: (cont: Continuation, fromLabel: string) => void
  onSelect: (stepId: string | null) => void
  onDetails: (stepId: string, trigger: HTMLElement) => void
}

function upstreamText(choice: Choice): string {
  if (!choice.has_more_upstream) return 'Ultimate source · nothing further upstream'
  const n = choice.upstream_choice_count
  return `${n} upstream ${n === 1 ? 'choice' : 'choices'}`
}

function terminalNote(count: number, atRoot: boolean): string {
  if (!atRoot) return 'Every choice here is an ultimate source; this is the end of the branch.'
  return `${count === 1 ? 'This mapping leads' : 'These mappings lead'} directly to the ultimate ${
    count === 1 ? 'source' : 'sources'
  }; there are no intermediate steps.`
}

/** Shows only the immediate choices; picking one marks it but does not move into the branch. */
export function ChoiceList({ choices, selectedStepId, detailStepId, atRoot, continuations, onTrack, onSelect, onDetails }: Props) {
  if (choices.length === 0) return <p className="status">No upstream lineage was found for this step.</p>
  const allTerminal = choices.every((c) => !c.has_more_upstream)
  return (
    <>
      {allTerminal && <p className="callout">{terminalNote(choices.length, atRoot)}</p>}
      <ul className="cards" aria-label="Upstream mappings">
        {choices.map((choice) => {
          const selected = choice.step_id === selectedStepId
          const endpoint = `${choice.source_object_name}.${choice.source_column_name}`
          return (
            <li key={choice.step_id} className="card-item">
              <button
                type="button"
                className={`card tone-${relationStyle(choice.relation_type).tone}${selected ? ' selected' : ''}`}
                aria-pressed={selected}
                onClick={() => onSelect(selected ? null : choice.step_id)}
              >
                <span className="card-title">{endpoint}</span>
                <span className="card-badges">
                  <RelationBadge type={choice.relation_type} />
                  <ConfidenceBadge value={choice.confidence_class} />
                </span>
                {(choice.driving_expression || choice.result_expression) && (
                  <span className="card-expr">
                    {choice.driving_expression && (
                      <span className="expr-line">
                        <span className="expr-tag when">When</span>
                        <code>{choice.driving_expression}</code>
                      </span>
                    )}
                    {choice.result_expression && (
                      <span className="expr-line">
                        <span className="expr-tag value">Value</span>
                        <code>{choice.result_expression}</code>
                      </span>
                    )}
                  </span>
                )}
                <span className="card-meta">
                  {choice.component_name ?? 'No component'}
                  {(choice.contributor_count ?? 1) > 1 && ` · ${choice.contributor_count} mappings`}
                </span>
                <span className="card-meta">{upstreamText(choice)}</span>
              </button>
              <button
                type="button"
                className="card-details"
                aria-label={`Details for ${endpoint}${choice.component_name ? `, ${choice.component_name}` : ''}`}
                aria-expanded={detailStepId === choice.step_id}
                onClick={(event) => onDetails(choice.step_id, event.currentTarget)}
              >
                Details
              </button>
              {continuations?.get(endpoint)?.map((cont) => (
                <button key={cont.project} type="button" className="card-track" onClick={() => onTrack?.(cont, endpoint)}>
                  Track in {cont.project} →
                </button>
              ))}
            </li>
          )
        })}
      </ul>
    </>
  )
}
