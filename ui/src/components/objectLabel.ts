import type { TargetObject } from '../api/types'

/** Same-named objects (for example from different source projects) get a qualifier. */
export function objectLabel(object: TargetObject, all: TargetObject[]): string {
  const duplicated = all.filter((o) => o.object_name === object.object_name).length > 1
  if (!duplicated) return object.object_name
  const processes = object.business_processes
    .map((p) => p.business_process_name)
    .filter((n): n is string => Boolean(n))
  const qualifiers = [object.source_project, ...processes].filter(Boolean)
  return `${object.object_name} (${qualifiers.join(' · ')})`
}
