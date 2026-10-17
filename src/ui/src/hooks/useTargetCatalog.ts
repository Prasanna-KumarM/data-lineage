import type { ApiClient } from '../api/client'
import type { Project, TargetColumn, TargetObject } from '../api/types'
import type { Selection } from '../state/selection'
import { useAsync } from './useAsync'

export function useTargetCatalog(client: ApiClient, selection: Selection) {
  const { project, objectId } = selection
  const projects = useAsync<Project[]>((signal) => client.projects(signal), 'projects')
  const targets = useAsync<TargetObject[]>(
    project ? (signal) => client.targets(project, signal) : null,
    `targets:${project}`,
  )
  const columns = useAsync<TargetColumn[]>(
    project && objectId ? (signal) => client.columns(project, objectId, signal) : null,
    `columns:${project}:${objectId}`,
  )
  return { projects, targets, columns }
}
