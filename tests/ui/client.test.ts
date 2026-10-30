import { ApiError, createApiClient } from '../../src/ui/src/api/client'
import { apiBase, describeReal, realClient } from './helpers'

describeReal('api client against the real lineage API', () => {
  it('lists projects', async () => {
    expect(await realClient().projects()).toEqual([{ project_name: 'SP_CLO' }])
  })

  it('lists target objects and columns', async () => {
    const client = realClient()
    const targets = await client.targets('SP_CLO')
    expect(targets).toHaveLength(5)
    const events = targets.find((o) => o.object_name === 'AR_PAR_LOAN_EVENTS')!
    expect(events.source_project).toBe('GP_SHARED')
    const columns = await client.columns('SP_CLO', events.object_id)
    expect(columns).toHaveLength(46)
    expect(columns.find((c) => c.column_name === 'MDE_CODE')?.step_count).toBe(3)
  })

  it('loads root choices and ultimate sources for a target', async () => {
    const client = realClient()
    const targets = await client.targets('SP_CLO')
    const trades = targets.find((o) => o.object_name === 'CM_PAR_LOAN_TRADES')!
    const column = (await client.columns('SP_CLO', trades.object_id)).find((c) => c.column_name === 'FDK_MT')!
    const target = { project: 'SP_CLO', objectId: trades.object_id, columnId: column.column_id }

    const upstream = await client.rootChoices(target)
    expect(upstream.choices).toHaveLength(1)
    const sources = await client.ultimateSources(target)
    expect(sources.terminal_sources.map((s) => s.column_name)).toEqual([
      'OFR_HTCS_BOOK_CODE',
      'OFR_HTC_BOOK_CODE',
      'OFR_HTS_BOOK_CODE',
    ])
  })

  it('sends the session id with every request', async () => {
    const seen: string[] = []
    const spy: typeof fetch = (input, init) => {
      seen.push(new Headers(init?.headers).get('X-Session-Id') ?? '')
      return fetch(input, init)
    }
    const client = realClient({ fetchImpl: spy, sessionId: 'abc-123' })
    await client.projects()
    await client.targets('SP_CLO')
    expect(seen).toEqual(['abc-123', 'abc-123'])
  })

  it('turns API errors into ApiError with the API code', async () => {
    const error = await realClient().targets('NOPE').catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, code: 'PROJECT_NOT_FOUND' })
  })

  it('reports an unreachable service as NETWORK_ERROR', async () => {
    const dead = createApiClient({ baseUrl: 'http://127.0.0.1:1', sessionId: 's' })
    const error = await dead.projects().catch((e) => e)
    expect(error).toMatchObject({ status: 0, code: 'NETWORK_ERROR' })
  })

  it('rethrows aborts instead of reporting them as errors', async () => {
    const controller = new AbortController()
    const pending = realClient().projects(controller.signal)
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('points at a running API', () => {
    expect(apiBase).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/)
  })
})
