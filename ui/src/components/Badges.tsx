import { relationStyle } from './relationStyle'

export function RelationBadge({ type }: { type: string }) {
  const { label, tone } = relationStyle(type)
  return (
    <span className={`badge tone-${tone}`} title={type}>
      {label}
    </span>
  )
}

export function ConfidenceBadge({ value }: { value: string | null }) {
  if (!value) return null
  return <span className={`badge confidence-${value.toLowerCase()}`}>{value}</span>
}
