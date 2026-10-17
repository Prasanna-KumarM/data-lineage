import type { Choice } from '../api/types'
import { ConfidenceBadge, RelationBadge } from './Badges'

interface Props {
  choices: Choice[]
  selectedStepId: string | null
  onSelect: (stepId: string | null) => void
}

function upstreamText(choice: Choice): string {
  if (!choice.has_more_upstream) return 'Ultimate source · nothing further upstream'
  const n = choice.upstream_choice_count
  return `${n} upstream ${n === 1 ? 'choice' : 'choices'}`
}

/** Shows only the immediate choices; picking one marks it but does not move into the branch. */
export function ChoiceList({ choices, selectedStepId, onSelect }: Props) {
  if (choices.length === 0) return <p className="status">No upstream lineage was found for this target.</p>
  const allTerminal = choices.every((c) => !c.has_more_upstream)
  return (
    <>
      {allTerminal && (
        <p className="status note">
          {choices.length === 1 ? 'This mapping leads' : 'These mappings lead'} directly to the ultimate
          {choices.length === 1 ? ' source' : ' sources'}; there are no intermediate steps.
        </p>
      )}
      <ul className="cards">
      {choices.map((choice) => {
        const selected = choice.step_id === selectedStepId
        return (
          <li key={choice.step_id}>
            <button
              type="button"
              className={`card${selected ? ' selected' : ''}`}
              aria-pressed={selected}
              onClick={() => onSelect(selected ? null : choice.step_id)}
            >
              <span className="card-title">
                {choice.source_object_name}.{choice.source_column_name}
              </span>
              <span className="card-badges">
                <RelationBadge type={choice.relation_type} />
                <ConfidenceBadge value={choice.confidence_class} />
              </span>
              <span className="card-meta">{choice.component_name ?? 'No component'}</span>
              <span className="card-meta">{upstreamText(choice)}</span>
            </button>
          </li>
        )
      })}
      </ul>
    </>
  )
}
