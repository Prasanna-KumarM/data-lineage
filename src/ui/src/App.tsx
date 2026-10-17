import { useMemo, useReducer } from 'react'
import { createApiClient, newSessionId, type ApiClient } from './api/client'
import type { TargetRef } from './api/types'
import { LineageWorkspace } from './components/LineageWorkspace'
import { TargetSelectors } from './components/TargetSelectors'
import { useTargetCatalog } from './hooks/useTargetCatalog'
import { emptySelection, selectionReducer } from './state/selection'

interface Props {
  client?: ApiClient
}

export default function App({ client: injected }: Props) {
  const client = useMemo(() => injected ?? createApiClient({ sessionId: newSessionId() }), [injected])
  const [selection, dispatch] = useReducer(selectionReducer, emptySelection)
  const catalog = useTargetCatalog(client, selection)

  const object =
    catalog.targets.status === 'success' ? catalog.targets.data.find((o) => o.object_id === selection.objectId) : undefined
  const column =
    catalog.columns.status === 'success' ? catalog.columns.data.find((c) => c.column_id === selection.columnId) : undefined

  const target: TargetRef | null =
    selection.project && object && column
      ? { project: selection.project, objectId: object.object_id, columnId: column.column_id }
      : null

  return (
    <div className="app">
      <header>
        <h1>Data Lineage</h1>
        <TargetSelectors catalog={catalog} selection={selection} dispatch={dispatch} />
      </header>
      <main>
        <LineageWorkspace
          client={client}
          target={target}
          object={object}
          column={column}
          allObjects={catalog.targets.status === 'success' ? catalog.targets.data : []}
        />
      </main>
    </div>
  )
}
