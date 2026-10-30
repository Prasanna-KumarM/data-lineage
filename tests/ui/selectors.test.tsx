import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import type { ApiClient } from '../../src/ui/src/api/client'
import type { TargetColumn, TargetObject } from '../../src/ui/src/api/types'
import { describeReal, realClient } from './helpers'

const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement
const optionTexts = (el: HTMLSelectElement) => Array.from(el.options).map((o) => o.textContent)

async function waitForObjects() {
  await waitFor(() => expect(optionTexts(select('Target Object')).length).toBeGreaterThan(1))
}

describeReal('selector workflow on the real SP_CLO lineage', () => {
  it('auto-selects the only project and lists its target objects', async () => {
    render(<App client={realClient()} />)
    await waitFor(() => expect(select('Project').value).toBe('SP_CLO'))
    await waitForObjects()
    expect(select('Target Object').disabled).toBe(false)
    expect(optionTexts(select('Target Object'))).toHaveLength(1 + 5)
    expect(select('Target Column').disabled).toBe(true)
  })

  it('lists the Target component once rather than duplicating intermediate root objects', async () => {
    render(<App client={realClient()} />)
    await waitForObjects()
    const labels = optionTexts(select('Target Object'))
    expect(labels).toContain('AR_PAR_LOAN_EVENTS')
    const events = labels.filter((l) => l === 'PAR_UNPROCESSED_EVENTS')
    expect(events).toHaveLength(1)
  })

  it('object selection loads its columns; column selection initializes the lineage session', async () => {
    const user = userEvent.setup()
    render(<App client={realClient()} />)
    await waitForObjects()
    await user.selectOptions(select('Target Object'), 'AR_PAR_LOAN_EVENTS')
    await waitFor(() => expect(optionTexts(select('Target Column'))).toHaveLength(1 + 46))
    expect(screen.getByText(/Select a project, target object and target column/)).toBeTruthy()

    await user.selectOptions(select('Target Column'), 'MDE_CODE')
    const panel = await screen.findByRole('region', { name: 'Lineage session' })
    expect(within(within(panel).getByRole('region', { name: 'Target' })).getByText('MDE_CODE')).toBeTruthy()
    expect(await within(panel).findAllByRole('button', { name: /^AR_CLO_ACCOUNTING_EVENTS\.e_product_group/ })).toHaveLength(1)
    const sources = within(panel).getByRole('region', { name: 'Ultimate sources' })
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(2))
  })

  it('shows a branching target with its choices and ultimate sources', async () => {
    const user = userEvent.setup()
    render(<App client={realClient()} />)
    await waitForObjects()
    await user.selectOptions(select('Target Object'), 'CM_PAR_LOAN_TRADES')
    await waitFor(() => expect(optionTexts(select('Target Column')).length).toBeGreaterThan(1))
    await user.selectOptions(select('Target Column'), 'FDK_MT')
    const panel = await screen.findByRole('region', { name: 'Lineage session' })
    expect(await within(panel).findAllByRole('button', { name: /^CM_CLO_OFFER\.e_fdk_mt/ })).toHaveLength(1)
    const sources = within(panel).getByRole('region', { name: 'Ultimate sources' })
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(3))
  })

  it('changing the target object resets the column and the lineage session', async () => {
    const user = userEvent.setup()
    render(<App client={realClient()} />)
    await waitForObjects()
    await user.selectOptions(select('Target Object'), 'AR_PAR_LOAN_EVENTS')
    await waitFor(() => expect(optionTexts(select('Target Column')).length).toBeGreaterThan(1))
    await user.selectOptions(select('Target Column'), 'MDE_CODE')
    await screen.findByRole('region', { name: 'Lineage session' })

    await user.selectOptions(select('Target Object'), 'CM_PAR_LOAN_TRADES')
    expect(select('Target Column').value).toBe('')
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Lineage session' })).toBeNull())
    expect(screen.getByText(/Select a project, target object and target column/)).toBeTruthy()
  })

  it('clearing the object returns to the initial state', async () => {
    const user = userEvent.setup()
    render(<App client={realClient()} />)
    await waitForObjects()
    await user.selectOptions(select('Target Object'), 'AR_PAR_LOAN_EVENTS')
    await waitFor(() => expect(select('Target Column').disabled).toBe(false))
    await user.selectOptions(select('Target Object'), '')
    expect(select('Target Column').disabled).toBe(true)
    expect(select('Target Column').value).toBe('')
  })

  it('shows loading while the service answers slowly', async () => {
    const slow: typeof fetch = async (input, init) => {
      await new Promise((r) => setTimeout(r, 150))
      return fetch(input, init)
    }
    render(<App client={realClient({ fetchImpl: slow })} />)
    expect(screen.getAllByRole('status')[0].textContent).toBe('Loading…')
    await waitForObjects()
  })

  it('shows an error with Retry when the service is unreachable', async () => {
    const calls: string[] = []
    const failing: typeof fetch = () => {
      calls.push('x')
      return Promise.reject(new TypeError('offline'))
    }
    const user = userEvent.setup()
    render(<App client={realClient({ fetchImpl: failing })} />)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('cannot be reached')
    expect(select('Project').disabled).toBe(true)
    await user.click(within(alert).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(calls.length).toBe(2))
  })
})

// Cases the single-project SP_CLO data cannot produce use a scripted client instead.
describe('selector workflow edge cases with a scripted client', () => {
  const objects = (prefix: string): TargetObject[] => [
    { object_id: `${prefix}-o1`, object_name: `${prefix}_ORDERS`, source_project: prefix, business_processes: [], column_count: 1 },
  ]
  const columns: TargetColumn[] = [{ column_id: 'c1', column_name: 'ID', step_count: 1 }]

  function scripted(overrides: Partial<ApiClient> = {}): ApiClient {
    return {
      projects: async () => [{ project_name: 'A' }, { project_name: 'B' }],
      targets: async (project) => objects(project),
      columns: async () => columns,
      rootChoices: async () => ({ choices: [] }),
      ultimateSources: async (t) => ({ project: t.project, object_id: t.objectId, column_id: t.columnId, step_id: null, terminal_sources: [] }),
      ...overrides,
    }
  }

  it('does not auto-select when there are several projects', async () => {
    render(<App client={scripted()} />)
    await waitFor(() => expect(optionTexts(select('Project'))).toHaveLength(3))
    expect(select('Project').value).toBe('')
    expect(select('Target Object').disabled).toBe(true)
  })

  it('changing the project resets object, column and the session', async () => {
    const user = userEvent.setup()
    render(<App client={scripted()} />)
    await waitFor(() => expect(optionTexts(select('Project'))).toHaveLength(3))
    await user.selectOptions(select('Project'), 'A')
    await waitFor(() => expect(optionTexts(select('Target Object'))).toHaveLength(2))
    await user.selectOptions(select('Target Object'), 'A_ORDERS')
    await waitFor(() => expect(optionTexts(select('Target Column'))).toHaveLength(2))
    await user.selectOptions(select('Target Column'), 'ID')
    await screen.findByRole('region', { name: 'Lineage session' })

    await user.selectOptions(select('Project'), 'B')
    expect(select('Target Object').value).toBe('')
    expect(select('Target Column').value).toBe('')
    await waitFor(() => expect(optionTexts(select('Target Object'))).toContain('B_ORDERS'))
    expect(optionTexts(select('Target Object'))).not.toContain('A_ORDERS')
    expect(screen.queryByRole('region', { name: 'Lineage session' })).toBeNull()
  })

  it('shows an empty state when a project has no target objects', async () => {
    const user = userEvent.setup()
    render(<App client={scripted({ targets: async () => [] })} />)
    await waitFor(() => expect(optionTexts(select('Project'))).toHaveLength(3))
    await user.selectOptions(select('Project'), 'A')
    expect(await screen.findByText('No target objects in this project.')).toBeTruthy()
    expect(select('Target Object').disabled).toBe(true)
  })

  it('shows the API message when loading targets fails', async () => {
    const { ApiError } = await import('../../src/ui/src/api/client')
    const user = userEvent.setup()
    render(<App client={scripted({ targets: async () => { throw new ApiError(503, 'DATABASE_UNAVAILABLE', 'The lineage database is unavailable.') } })} />)
    await waitFor(() => expect(optionTexts(select('Project'))).toHaveLength(3))
    await user.selectOptions(select('Project'), 'A')
    expect((await screen.findByRole('alert')).textContent).toContain('The lineage database is unavailable.')
  })

  it('ignores a late answer for a project that is no longer selected', async () => {
    const resolvers: Record<string, (v: TargetObject[]) => void> = {}
    const client = scripted({ targets: (project) => new Promise((resolve) => { resolvers[project] = resolve }) })
    const user = userEvent.setup()
    render(<App client={client} />)
    await waitFor(() => expect(optionTexts(select('Project'))).toHaveLength(3))
    await user.selectOptions(select('Project'), 'A')
    await user.selectOptions(select('Project'), 'B')
    resolvers.B(objects('B'))
    await waitFor(() => expect(optionTexts(select('Target Object'))).toContain('B_ORDERS'))
    resolvers.A(objects('A'))
    await new Promise((r) => setTimeout(r, 50))
    expect(optionTexts(select('Target Object'))).toEqual(['Select a target object', 'B_ORDERS'])
  })
})
