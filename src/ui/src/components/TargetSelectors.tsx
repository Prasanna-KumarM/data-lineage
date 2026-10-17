import { useEffect } from 'react'
import type { Selection, SelectionAction } from '../state/selection'
import { useTargetCatalog } from '../hooks/useTargetCatalog'
import { objectLabel } from './objectLabel'
import { SelectorField } from './SelectorField'

interface Props {
  catalog: ReturnType<typeof useTargetCatalog>
  selection: Selection
  dispatch: (action: SelectionAction) => void
}

export function TargetSelectors({ catalog, selection, dispatch }: Props) {
  const { projects, targets, columns } = catalog

  const projectOptions = projects.status === 'success' ? projects.data.map((p) => ({ value: p.project_name, label: p.project_name })) : []
  const objectOptions =
    selection.project && targets.status === 'success'
      ? targets.data.map((o) => ({ value: o.object_id, label: objectLabel(o, targets.data) }))
      : selection.project
        ? []
        : null
  const columnOptions =
    selection.objectId && columns.status === 'success'
      ? columns.data.map((c) => ({ value: c.column_id, label: c.column_name }))
      : selection.objectId
        ? []
        : null

  // A single project needs no choice.
  useEffect(() => {
    if (projects.status === 'success' && projects.data.length === 1 && selection.project === null) {
      dispatch({ type: 'project', value: projects.data[0].project_name })
    }
  }, [projects, selection.project, dispatch])

  return (
    <div className="selectors">
      <SelectorField
        id="project"
        label="Project"
        placeholder="Select a project"
        emptyMessage="No projects available."
        state={projects}
        options={projectOptions}
        value={selection.project}
        onChange={(value) => dispatch({ type: 'project', value })}
      />
      <SelectorField
        id="target-object"
        label="Target Object"
        placeholder="Select a target object"
        emptyMessage="No target objects in this project."
        state={targets}
        options={objectOptions}
        value={selection.objectId}
        onChange={(value) => dispatch({ type: 'object', value })}
      />
      <SelectorField
        id="target-column"
        label="Target Column"
        placeholder="Select a target column"
        emptyMessage="No columns with lineage for this object."
        state={columns}
        options={columnOptions}
        value={selection.columnId}
        onChange={(value) => dispatch({ type: 'column', value })}
      />
    </div>
  )
}
