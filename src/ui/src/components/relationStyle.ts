export type Tone = 'direct' | 'auto' | 'expression' | 'constant' | 'lookup' | 'function' | 'not-persisted' | 'neutral'

const known: Record<string, { label: string; tone: Tone }> = {
  EXPLICIT_INATTR: { label: 'Direct mapping', tone: 'direct' },
  EXPLICIT_PATHFROM_PATHTO: { label: 'Direct mapping (path)', tone: 'direct' },
  AUTO_MAP_BY_NAME: { label: 'Auto-mapped by name', tone: 'auto' },
  TRANSFORMATION_AUTO_MAP_BY_NAME: { label: 'Transformation auto-map', tone: 'auto' },
  EXPRESSION: { label: 'Expression', tone: 'expression' },
  CONSTANT_ASSIGNMENT: { label: 'Constant', tone: 'constant' },
  ENRICHMENT_LOOKUP: { label: 'Lookup', tone: 'lookup' },
  RUNTIME_FUNCTION_ASSIGNMENT: { label: 'Function', tone: 'function' },
  NOT_PERSISTED: { label: 'Not persisted', tone: 'not-persisted' },
}

function humanize(type: string): string {
  const text = type.toLowerCase().replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function relationStyle(type: string): { label: string; tone: Tone } {
  return known[type] ?? { label: humanize(type), tone: 'neutral' }
}
