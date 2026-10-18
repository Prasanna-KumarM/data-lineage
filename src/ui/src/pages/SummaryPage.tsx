import { useEffect, useState } from 'react'
import type { ApiClient } from '../api/client'
import type { TargetObject } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { formatRoute, useNavigate, type Route } from '../routing'
import { ErrorNotice, LoadingNotice } from '../components/Notices'
import { objectLabel } from '../components/objectLabel'
import { SummaryTable } from '../components/SummaryTable'
import { TableSearch } from '../components/TableSearch'

type SummaryRoute = Extract<Route, { name: 'summary' }>

interface Props {
  client: ApiClient
  route: SummaryRoute
}

/** Landing page: find a target table, then see every column with its paths and ultimate sources. */
export function SummaryPage({ client, route }: Props) {
  const navigate = useNavigate()
  const projects = useAsync((signal) => client.projects(signal), 'projects')
  const [chosenProject, setChosenProject] = useState<string | null>(null)

  const names = projects.status === 'success' ? projects.data.map((p) => p.project_name) : []
  const project = route.project ?? chosenProject ?? (names.length === 1 ? names[0] : null)

  useEffect(() => {
    if (route.project === null && chosenProject === null && names.length === 1) setChosenProject(names[0])
  }, [route.project, chosenProject, names])

  const summary = useAsync(
    project && route.objectId ? (signal) => client.tableSummary(project, route.objectId!, signal) : null,
    `summary:${project}:${route.objectId}`,
  )

  const open = (object: TargetObject) => navigate({ name: 'summary', project, objectId: object.object_id })

  return (
    <main className="page">
      {projects.status === 'loading' && <LoadingNotice text="Loading projects…" />}
      {projects.status === 'error' && <ErrorNotice error={projects.error} onRetry={projects.reload} />}

      {projects.status === 'success' && names.length === 0 && <p className="status">No projects available.</p>}
      {projects.status === 'success' && names.length > 1 && (
        <div className="field project-field">
          <label htmlFor="summary-project">Project</label>
          <select
            id="summary-project"
            value={project ?? ''}
            onChange={(e) => {
              setChosenProject(e.target.value || null)
              navigate({ name: 'summary', project: e.target.value || null, objectId: null })
            }}
          >
            <option value="">Select a project</option>
            {names.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      )}

      {project && !route.objectId && <TableSearch client={client} project={project} onChoose={open} />}

      {project && route.objectId && (
        <>
          <nav className="crumbs" aria-label="Summary navigation">
            <a href={formatRoute({ name: 'summary', project, objectId: null })}>← All target tables</a>
          </nav>
          {summary.status === 'loading' && <LoadingNotice text="Loading table summary…" />}
          {summary.status === 'error' && <ErrorNotice error={summary.error} onRetry={summary.reload} />}
          {summary.status === 'success' && (
            <>
              <header className="table-head">
                <h2>{objectLabel(summary.data.object, [summary.data.object])}</h2>
                <p className="card-meta">
                  {summary.data.object.source_project && `${summary.data.object.source_project} · `}
                  {summary.data.object.business_processes.map((p) => p.business_process_name).join(', ')}
                </p>
                <p className="table-totals">
                  {summary.data.totals.columns} columns · {summary.data.totals.with_lineage} with lineage
                </p>
              </header>
              <SummaryTable
                key={`${project}/${route.objectId}`}
                summary={summary.data}
                onOpenColumn={(column) =>
                  navigate({ name: 'lineage', project, objectId: route.objectId, columnId: column.column_id })
                }
              />
            </>
          )}
        </>
      )}
    </main>
  )
}
