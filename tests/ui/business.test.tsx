import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import type { ApiClient } from '../../src/ui/src/api/client'
import type { Project, TargetObject } from '../../src/ui/src/api/types'

function show(client: ApiClient, hash: string) {
  cleanup()
  window.history.replaceState(null, '', hash)
  const user = userEvent.setup()
  render(<App client={client} />)
  return user
}

const table = (id: string, name: string, columns: number): TargetObject => ({
  object_id: id,
  object_name: name,
  source_project: null,
  business_processes: [],
  column_count: columns,
})

const catalogProjects: Project[] = [
  { project_name: 'SP_CLO', value_chain: 'Lending', source_system: 'CLO', target_system: 'GFRS', business_tables: ['PAR_GFRS_CLO_TRADES'], catalog_order: 2 },
  { project_name: 'SP_LIQ', value_chain: 'Lending', source_system: 'Loan IQ', target_system: 'GFRS', business_tables: ['PAR_GFRS_LIQ_TRADES'], catalog_order: 0 },
  {
    project_name: 'SP_TFS_TIP',
    value_chain: 'Trade Finance',
    source_system: 'Ti Plus',
    target_system: 'GFRS',
    business_tables: ['PAR_GFRS_TFS_TRADES', 'PAR_GFRS_TFS_CHARGES'],
    catalog_order: 1,
    ready: false,
    startable: false,
    problem: 'Listed in the catalog, but no database was found.',
  },
]

const TABLES: Record<string, TargetObject[]> = {
  SP_CLO: [table('TCLO', 'PAR_GFRS_CLO_TRADES', 42), table('TCLO2', 'CM_CLO_INTERNAL', 9)],
  SP_LIQ: [table('TLIQ', 'PAR_GFRS_LIQ_TRADES', 226)],
}

const client: ApiClient = {
  projects: async () => catalogProjects,
  analysisStats: async () => ({
    business_processes: 2,
    components: 10,
    mappings: 20,
    lineage_paths: 5,
    target_columns: 2,
    target_columns_with_lineage: 2,
  }),
  targets: async (project) => TABLES[project] ?? [],
  columns: async () => [],
  searchTargets: async () => [],
  tableSummary: async () => {
    throw new Error('unused')
  },
  rootChoices: async () => ({ choices: [] }),
  upstream: async () => ({ choices: [] }),
  remainingDepth: async () => {
    throw new Error('unused')
  },
  stepDetail: async () => {
    throw new Error('unused')
  },
  ultimateSources: async (t) => ({ project: t.project, object_id: t.objectId, column_id: t.columnId, step_id: null, terminal_sources: [] }),
}

const listNames = () => within(screen.getByRole('list', { name: 'Target tables' })).getAllByRole('listitem').map((li) => li.textContent ?? '')

describe('business view of the summary landing page', () => {
  it('is the default and lists only cataloged tables with their business subtitle', async () => {
    const user = show(client, '#/summary')
    await screen.findByText(/PAR_GFRS_LIQ_TRADES/)
    const names = listNames()
    expect(names.some((t) => t.includes('PAR_GFRS_CLO_TRADES'))).toBe(true)
    expect(names.some((t) => t.includes('PAR_GFRS_LIQ_TRADES'))).toBe(true)
    expect(names.some((t) => t.includes('CM_CLO_INTERNAL'))).toBe(false)
    expect(names.find((t) => t.includes('PAR_GFRS_LIQ_TRADES'))).toContain('Lending · Loan IQ · GFRS · SP_LIQ')
    expect(names.find((t) => t.includes('PAR_GFRS_LIQ_TRADES'))).toContain('226 columns')
    expect((await screen.findByRole('button', { name: 'Business' })).getAttribute('aria-pressed')).toBe('true')
    await user.click(screen.getByRole('button', { name: /notes? about the listed projects/ }))
    expect(screen.getByText(/SP_TFS_TIP: Listed in the catalog/)).toBeTruthy()
  })

  it('shows what the tool analyzed above the table list', async () => {
    show(client, '#/summary')
    await screen.findByText(/PAR_GFRS_LIQ_TRADES/)
    const bar = await screen.findByRole('note', { name: 'What the tool analyzed' })
    expect(bar.textContent).toContain('Business processes analyzed')
    expect(bar.textContent).toContain('Components identified')
    expect(bar.textContent).toContain('Mappings uncovered')
    expect(bar.textContent).toContain('Lineage paths created')
    expect(bar.textContent).toContain('Target columns covered')
    expect(bar.textContent).toContain('2/2')
  })

  it('filters tables by value chain', async () => {
    const user = show(client, '#/summary')
    await screen.findByText(/PAR_GFRS_LIQ_TRADES/)
    await user.selectOptions(screen.getByLabelText('Value chain'), 'Trade Finance')
    expect(screen.getByText('No target tables match.')).toBeTruthy()
    expect(screen.queryByText(/PAR_GFRS_LIQ_TRADES/)).toBeNull()
    await user.selectOptions(screen.getByLabelText('Value chain'), 'Lending')
    await screen.findByText(/PAR_GFRS_LIQ_TRADES/)
    const names = listNames()
    expect(names.some((t) => t.includes('PAR_GFRS_CLO_TRADES'))).toBe(true)
    expect(names.some((t) => t.includes('PAR_GFRS_LIQ_TRADES'))).toBe(true)
  })

  it('preselects the value chain and target system of the first catalog row', async () => {
    show(client, '#/summary')
    await screen.findByText(/PAR_GFRS_LIQ_TRADES/)
    expect((screen.getByLabelText('Value chain') as HTMLSelectElement).value).toBe('Lending')
    expect((screen.getByLabelText('Target system') as HTMLSelectElement).value).toBe('GFRS')
  })

  it('filters tables by target system', async () => {
    const user = show(client, '#/summary')
    await screen.findByText(/PAR_GFRS_LIQ_TRADES/)
    await user.selectOptions(screen.getByLabelText('Target system'), 'GFRS')
    expect(listNames().length).toBe(2)
  })

  it('switches to the developer view and back', async () => {
    const user = show(client, '#/summary')
    await screen.findByText(/PAR_GFRS_LIQ_TRADES/)
    await user.click(await screen.findByRole('button', { name: 'Developer' }))
    expect(await screen.findByLabelText('Project')).toBeTruthy()
    await user.click(await screen.findByRole('button', { name: 'Business' }))
    expect(await screen.findByText(/PAR_GFRS_LIQ_TRADES/)).toBeTruthy()
  })

  it('opens a table inside its own project', async () => {
    const user = show(client, '#/summary')
    await user.click(await screen.findByText(/PAR_GFRS_LIQ_TRADES/))
    expect(window.location.hash).toBe('#/summary/SP_LIQ/TLIQ')
  })
})
