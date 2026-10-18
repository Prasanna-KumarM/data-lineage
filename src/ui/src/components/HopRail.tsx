import type { Choice, RemainingDepth } from '../api/types'
import type { AsyncState } from '../hooks/useAsync'
import { relationStyle } from './relationStyle'

const MAX_HOLLOW_DOTS = 12

interface Props {
  /** Hops already taken, in order. */
  path: Choice[]
  /** The highlighted choice that has not been advanced into yet. */
  selected: Choice | undefined
  /** Remaining depth of the active branch; idle when there is no active branch. */
  depth: AsyncState<RemainingDepth>
  onJump: (depth: number) => void
}

const endpoint = (c: Choice) => `${c.source_object_name}.${c.source_column_name}`
const hops = (n: number) => `${n} ${n === 1 ? 'hop' : 'hops'}`

/** The last hop of every branch reaches an ultimate source, which has its own panel, so it is not counted here. */
function pathHops(d: RemainingDepth) {
  const less = (n: number | null) => (n === null ? null : Math.max(0, n - 1))
  return { exact: less(d.remaining_hops_exact), min: less(d.remaining_hops_min) ?? 0, max: less(d.remaining_hops_max) ?? 0 }
}

function summary(depth: AsyncState<RemainingDepth>): string {
  switch (depth.status) {
    case 'idle':
      return 'Select a mapping to see how many hops remain on that branch.'
    case 'loading':
      return 'Calculating remaining hops…'
    case 'error':
      return 'Remaining hops are unavailable.'
    case 'success': {
      const d = depth.data
      if (d.is_terminal) return 'End of this branch.'
      const h = pathHops(d)
      if (h.exact !== null) return h.exact === 0 ? 'Next: the ultimate sources.' : `${hops(h.exact)} remaining.`
      return h.min === 0 ? `Up to ${hops(h.max)} remaining.` : `${h.min}–${h.max} hops remaining.`
    }
  }
}

/** One dot per hop on the branch being followed; sibling mappings never get dots. */
export function HopRail({ path, selected, depth, onJump }: Props) {
  const remaining = depth.status === 'success' ? depth.data : null
  const counted = remaining ? pathHops(remaining) : null
  const hollow = counted ? (counted.exact ?? counted.min) : 0
  const variable = counted !== null && counted.exact === null

  return (
    <div className="rail" role="group" aria-label="Hop progress">
      <ol className="rail-dots">
        {path.map((hop, index) => (
          <li key={hop.step_id}>
            <button
              type="button"
              className="dot filled"
              aria-label={`Hop ${index + 1}: ${endpoint(hop)}, ${relationStyle(hop.relation_type).label}. Go back to this hop.`}
              title={`Hop ${index + 1}: ${endpoint(hop)} (${relationStyle(hop.relation_type).label})`}
              onClick={() => onJump(index)}
            >
              ●
            </button>
          </li>
        ))}
        {selected && (
          <li>
            <span
              className="dot current"
              role="img"
              aria-label={`Selected hop ${path.length + 1}: ${endpoint(selected)}`}
              title={`Hop ${path.length + 1}: ${endpoint(selected)} (selected)`}
            >
              ◉
            </span>
          </li>
        )}
        {Array.from({ length: Math.min(hollow, MAX_HOLLOW_DOTS) }, (_, i) => (
          <li key={`rest-${i}`}>
            <span className="dot hollow" role="img" aria-label="Remaining hop">
              ○
            </span>
          </li>
        ))}
        {(variable || hollow > MAX_HOLLOW_DOTS) && (
          <li>
            <span className="dot more" role="img" aria-label="More hops, number not fixed">
              ⋯
            </span>
          </li>
        )}
      </ol>
      <p className="rail-summary" aria-live="polite">
        {summary(depth)}
      </p>
    </div>
  )
}

export function Breadcrumb({ targetLabel, path, selected }: { targetLabel: string; path: Choice[]; selected: Choice | undefined }) {
  return (
    <nav className="breadcrumb" aria-label="Lineage path">
      <ol>
        <li>{targetLabel}</li>
        {path.map((hop) => (
          <li key={hop.step_id}>{endpoint(hop)}</li>
        ))}
        {selected && (
          <li aria-current="step" className="breadcrumb-selected">
            {endpoint(selected)}
          </li>
        )}
      </ol>
    </nav>
  )
}
