import { useEffect, useReducer } from 'react'
import type { ApiClient } from '../api/client'
import type { TargetRef } from '../api/types'
import { LineageWorkspace } from '../components/LineageWorkspace'
import { TargetSelectors } from '../components/TargetSelectors'
import { useTargetCatalog } from '../hooks/useTargetCatalog'
import { formatRoute, replaceRoute, type Route } from '../routing'
import { selectionReducer } from '../state/selection'

type LineageRoute = Extract<Route, { name: 'lineage' }>

interface Props {
  client: ApiClient
  route: LineageRoute
}

/** The walkthrough: pick a target column (or arrive from the summary) and follow its lineage hop by hop. */
export function LineagePage({ client, route }: Props) {
  const [selection, dispatch] = useReducer(selectionReducer, {
    project: route.project,
    objectId: route.objectId,
    columnId: route.columnId,
  })
  const catalog = useTargetCatalog(client, selection)

  // The address follows the selectors so that the page can be bookmarked or shared.
  useEffect(() => {
    replaceRoute({ name: 'lineage', ...selection })
  }, [selection])

  const objects = catalog.targets.status === 'success' ? catalog.targets.data : []
  const object = objects.find((o) => o.object_id === selection.objectId)
  const column =
    catalog.columns.status === 'success' ? catalog.columns.data.find((c) => c.column_id === selection.columnId) : undefined

  const target: TargetRef | null =
    selection.project && object && column
      ? { project: selection.project, objectId: object.object_id, columnId: column.column_id }
      : null

  const notFound =
    (selection.objectId && catalog.targets.status === 'success' && !object) ||
    (selection.columnId && catalog.columns.status === 'success' && !column)

  return (
    <>
      <div className="subbar">
        <TargetSelectors catalog={catalog} selection={selection} dispatch={dispatch} />
        <a className="back-link" href={formatRoute({ name: 'summary', project: selection.project, objectId: selection.objectId })}>
          ← Back to summary
        </a>
      </div>
      <main className="page">
        {notFound && (
          <p className="status error" role="alert">
            That table or column is not in the current lineage data. Pick another one above.
          </p>
        )}
        <LineageWorkspace client={client} target={target} object={object} column={column} allObjects={objects} />
      </main>
    </>
  )
}
