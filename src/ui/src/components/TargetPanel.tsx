import type { TargetColumn, TargetObject } from '../api/types'
import { objectLabel } from './objectLabel'

interface Props {
  project: string
  object: TargetObject
  allObjects: TargetObject[]
  column: TargetColumn
}

/** The original target; it never changes while the user walks the lineage. */
export function TargetPanel({ project, object, allObjects, column }: Props) {
  const processes = object.business_processes.map((p) => p.business_process_name).filter(Boolean)
  return (
    <section className="panel target-panel" aria-label="Target">
      <h2 className="panel-title">Target</h2>
      <p className="target-object">{objectLabel(object, allObjects)}</p>
      <p className="target-column">{column.column_name}</p>
      <dl className="facts">
        <dt>Project</dt>
        <dd>{project}</dd>
        {object.source_project && (
          <>
            <dt>Source project</dt>
            <dd>{object.source_project}</dd>
          </>
        )}
        {processes.length > 0 && (
          <>
            <dt>Business process</dt>
            <dd>{processes.join(', ')}</dd>
          </>
        )}
      </dl>
    </section>
  )
}
