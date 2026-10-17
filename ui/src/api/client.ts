import type {
  Project,
  TargetColumn,
  TargetObject,
  TargetRef,
  UltimateSourcesResponse,
  UpstreamResponse,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export interface ApiClient {
  projects(signal?: AbortSignal): Promise<Project[]>
  targets(project: string, signal?: AbortSignal): Promise<TargetObject[]>
  columns(project: string, objectId: string, signal?: AbortSignal): Promise<TargetColumn[]>
  rootChoices(target: TargetRef, signal?: AbortSignal): Promise<UpstreamResponse>
  upstream(stepId: string, signal?: AbortSignal): Promise<UpstreamResponse>
  ultimateSources(target: TargetRef, signal?: AbortSignal, stepId?: string): Promise<UltimateSourcesResponse>
}

export interface ApiClientOptions {
  sessionId: string
  baseUrl?: string
  fetchImpl?: typeof fetch
}

export function createApiClient({ sessionId, baseUrl = '', fetchImpl }: ApiClientOptions): ApiClient {
  async function get<T>(path: string, params: Record<string, string>, signal?: AbortSignal): Promise<T> {
    const query = new URLSearchParams(params).toString()
    const url = `${baseUrl}${path}${query ? `?${query}` : ''}`
    let response: Response
    try {
      const doFetch = fetchImpl ?? fetch
      response = await doFetch(url, { headers: { 'X-Session-Id': sessionId }, signal })
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      throw new ApiError(0, 'NETWORK_ERROR', 'The lineage service cannot be reached.')
    }
    if (!response.ok) {
      let code = 'HTTP_ERROR'
      let message = `The lineage service returned status ${response.status}.`
      try {
        const body = await response.json()
        if (body?.error?.code) {
          code = body.error.code
          message = body.error.message
        }
      } catch {
        // Non-JSON error body: keep the generic message.
      }
      throw new ApiError(response.status, code, message)
    }
    return (await response.json()) as T
  }

  const targetParams = (t: TargetRef) => ({ project: t.project, object_id: t.objectId, column_id: t.columnId })

  return {
    projects: (signal) => get('/projects', {}, signal),
    targets: (project, signal) => get('/targets', { project }, signal),
    columns: (project, objectId, signal) =>
      get(`/targets/${encodeURIComponent(objectId)}/columns`, { project }, signal),
    rootChoices: (target, signal) => get('/lineage/upstream', targetParams(target), signal),
    upstream: (stepId, signal) => get('/lineage/upstream', { step_id: stepId }, signal),
    ultimateSources: (target, signal, stepId) =>
      get('/lineage/ultimate-sources', { ...targetParams(target), ...(stepId ? { step_id: stepId } : {}) }, signal),
  }
}

export function newSessionId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `s-${Date.now()}-${Math.random().toString(36).slice(2)}`
}
