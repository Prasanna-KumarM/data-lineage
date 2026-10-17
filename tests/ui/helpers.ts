import { createApiClient } from '../../ui/src/api/client'

export const apiBase = process.env.TEST_API_BASE

// Real-API tests need the SP_CLO lineage DB; without it they are skipped, not faked.
export const describeReal = apiBase ? describe : describe.skip

export function realClient(overrides: { fetchImpl?: typeof fetch; sessionId?: string } = {}) {
  return createApiClient({ baseUrl: apiBase, sessionId: overrides.sessionId ?? 'ui-test', fetchImpl: overrides.fetchImpl })
}
