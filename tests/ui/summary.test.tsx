import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import type { ApiClient } from '../../src/ui/src/api/client'
import type { SummaryColumn, TableSummary } from '../../src/ui/src/api/types'
import { describeReal, realClient } from './helpers'

function show(client: ApiClient, hash: string) {
  cleanup()
  window.history.replaceState(null, '', hash)
  const user = userEvent.setup()
  render(<App client={client} />)
  return user
}

async function ids(objectName: string, sourceProject?: string) {
  const objects = await realClient().targets('SP_CLO')
  const object = objects.find((o) => o.object_name === objectName && (sourceProject === undefined || o.source_project === sourceProject))!
  return object.object_id
}

async function openTable(objectName: string, client: ApiClient = realClient()) {
  const objectId = await ids(objectName)
  const user = show(client, `#/summary/SP_CLO/${objectId}`)
  const table = await screen.findByRole('table')
  return { user, table, objectId }
}

const rowOf = (name: string) => screen.getByRole('button', { name, exact: true }).closest('tr') as HTMLTableRowElement
const textOf = (el: Element | null) => el?.textContent ?? ''

describeReal('summary landing page on the real SP_CLO lineage', () => {
  it('lists every target table with its column count', async () => {
    show(realClient(), '#/summary')
    const list = await screen.findByRole('list', { name: 'Target tables' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(5)
    expect(textOf(items[0])).toContain('AR_PAR_LOAN_EVENTS')
    expect(textOf(items[0])).toContain('46 columns')
    expect(textOf(items[0])).not.toContain('AR_CLO_EVENT_PROCESSING')
    expect((screen.getByLabelText('Project') as HTMLSelectElement).value).toBe('SP_CLO')
  })

  it('lists Aptitude targets once instead of listing intermediate roots as duplicate targets', async () => {
    show(realClient(), '#/summary')
    const list = await screen.findByRole('list', { name: 'Target tables' })
    const events = within(list).getAllByRole('listitem').map(textOf).filter((t) => t.includes('PAR_UNPROCESSED_EVENTS'))
    expect(events).toHaveLength(1)
    expect(events[0]).toContain('35 columns')
  })

  it('narrows the list as the user types, ignoring case', async () => {
    const user = show(realClient(), '#/summary')
    const box = await screen.findByLabelText('Search target tables')
    await within(await screen.findByRole('list', { name: 'Target tables' })).findAllByRole('listitem')

    await user.type(box, 'gfrs')
    await waitFor(() => expect(within(screen.getByRole('list', { name: 'Target tables' })).getAllByRole('listitem')).toHaveLength(1))
    expect(textOf(screen.getByRole('list', { name: 'Target tables' }))).toContain('PAR_GFRS_CLO_TRADES')

    await user.clear(box)
    await user.type(box, 'LOAN')
    await waitFor(() => expect(within(screen.getByRole('list', { name: 'Target tables' })).getAllByRole('listitem')).toHaveLength(2))

    await user.clear(box)
    await user.type(box, 'no_such_table')
    expect(await screen.findByText('No target tables match.')).toBeTruthy()

    await user.clear(box)
    await waitFor(() => expect(within(screen.getByRole('list', { name: 'Target tables' })).getAllByRole('listitem')).toHaveLength(5))
  })

  it('opens a table from the list and can return to the list', async () => {
    const user = show(realClient(), '#/summary')
    const list = await screen.findByRole('list', { name: 'Target tables' })
    await user.click(within(list).getByRole('button', { name: /AR_PAR_LOAN_EVENTS/ }))
    await screen.findByRole('table')
    const objectId = await ids('AR_PAR_LOAN_EVENTS')
    expect(window.location.hash).toBe(`#/summary/SP_CLO/${objectId}`)
    expect(screen.getByRole('heading', { name: 'AR_PAR_LOAN_EVENTS' })).toBeTruthy()
    expect(document.body.textContent).toContain('46 columns · 46 with lineage')
    expect(document.body.textContent).not.toContain('AR_CLO_EVENT_PROCESSING')

    await user.click(screen.getByRole('link', { name: '← All target tables' }))
    expect(await screen.findByRole('list', { name: 'Target tables' })).toBeTruthy()
    expect(window.location.hash).toBe('#/summary/SP_CLO')
  })

  it('shows an error for a table that is not in the data', async () => {
    show(realClient(), '#/summary/SP_CLO/OBJ_nope')
    expect((await screen.findByRole('alert')).textContent).toContain('Unknown target object')
  })

  it('reports a failed load and recovers on Retry', async () => {
    let fail = true
    const flaky: typeof fetch = (input, init) =>
      fail && String(input).includes('/summary')
        ? Promise.resolve(new Response(JSON.stringify({ error: { code: 'DATABASE_UNAVAILABLE', message: 'The lineage database is unavailable.' } }), { status: 503 }))
        : fetch(input, init)
    const objectId = await ids('CM_PAR_LOAN_TRADES')
    const user = show(realClient({ fetchImpl: flaky }), `#/summary/SP_CLO/${objectId}`)
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('The lineage database is unavailable.')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('table')).toBeTruthy()
  })
})

describeReal('table summary on the real SP_CLO lineage', () => {
  it('is a three-column table: column, paths, ultimate sources', async () => {
    const { table } = await openTable('CM_PAR_LOAN_TRADES')
    expect(within(table).getAllByRole('columnheader').map(textOf)).toEqual(['Column', 'Paths', 'Ultimate sources'])
    expect(within(table).getAllByRole('row')).toHaveLength(1 + 26)
  })

  it('shows counts and hop ranges, with the ultimate sources open and the paths collapsed', async () => {
    await openTable('CM_PAR_LOAN_TRADES')
    const row = rowOf('FDK_MT')
    const paths = within(row).getByRole('button', { name: 'Paths of FDK_MT' })
    const sources = within(row).getByRole('button', { name: 'Ultimate sources of FDK_MT' })
    expect(textOf(paths)).toContain('3 paths · 4 hops')
    expect(textOf(sources)).toContain('3 sources')
    expect(paths.getAttribute('aria-expanded')).toBe('false')
    expect(sources.getAttribute('aria-expanded')).toBe('true')
    expect(screen.queryAllByRole('list', { name: /^Paths of/ })).toHaveLength(0)
    expect(screen.getAllByRole('list', { name: /^Ultimate sources of/ })).toHaveLength(26)
  })

  it('expands to one line per ultimate source with its hop count and route', async () => {
    const { user } = await openTable('CM_PAR_LOAN_TRADES')
    const row = rowOf('FDK_MT')
    await user.click(within(row).getByRole('button', { name: 'Paths of FDK_MT' }))
    const list = within(row).getByRole('list', { name: 'Paths of FDK_MT' })
    const lines = within(list).getAllByRole('listitem')
    expect(lines).toHaveLength(3)
    for (const line of lines) {
      expect(line.querySelector('.hops-badge')?.textContent).toBe('4 hops')
      expect(textOf(line)).not.toContain('routes')
    }
    expect(textOf(lines[0].querySelector('.route'))).toBe(
      'FDK_MT ← CM_CLO_OFFER.e_fdk_mt ← FSD_FO_DESKS.FDK_MT ← CM_CLO_OFFER.e_bok_code ← CM_CLO_OFFER.OFR_HTCS_BOOK_CODE',
    )
    expect(lines[0].querySelector('.route-node[title]')?.getAttribute('title')).toContain('CM_CLO_OFR')

    await user.click(within(row).getByRole('button', { name: 'Paths of FDK_MT' }))
    expect(within(row).queryByRole('list', { name: 'Paths of FDK_MT' })).toBeNull()
  })

  it('lists the ultimate sources with their kind, and collapses them on request', async () => {
    const { user } = await openTable('CM_PAR_LOAN_TRADES')
    const row = rowOf('FDK_MT')
    const items = within(within(row).getByRole('list', { name: 'Ultimate sources of FDK_MT' })).getAllByRole('listitem')
    expect(items.map((i) => i.querySelector('.source-name')?.textContent)).toEqual([
      'CM_CLO_OFFER.OFR_HTCS_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTC_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTS_BOOK_CODE',
    ])
    expect(items.every((i) => i.querySelector('.badge.kind-column')?.textContent === 'Column')).toBe(true)
    await user.click(within(row).getByRole('button', { name: 'Ultimate sources of FDK_MT' }))
    expect(within(row).queryByRole('list', { name: 'Ultimate sources of FDK_MT' })).toBeNull()
  })

  it('shows CASE branches to one constant as separate sources with their conditions', async () => {
    await openTable('AR_PAR_LOAN_EVENTS')
    const row = rowOf('PDT_CODE')
    expect(textOf(within(row).getByRole('button', { name: 'Paths of PDT_CODE' }))).toContain('2 paths · 2 hops')
    const items = within(within(row).getByRole('list', { name: 'Ultimate sources of PDT_CODE' })).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items.map((i) => i.querySelector('.source-condition')?.textContent)).toEqual([
      'when AEF_EVENT_CODE=="E011"',
      'when ELSE',
    ])
    for (const item of items) {
      expect(item.querySelector('.badge.kind-constant')?.textContent).toBe('Constant')
      expect(textOf(item)).toContain('Value "OFFER"')
    }
    const flags = Array.from(row.querySelectorAll('.badge.flag')).map(textOf)
    expect(flags).toEqual(expect.arrayContaining(['Constant', 'CASE']))
  })

  it('marks constants, functions and not-persisted columns', async () => {
    await openTable('CM_PAR_LOAN_TRADES')
    const flagsOf = (name: string) => Array.from(rowOf(name).querySelectorAll('.badge.flag')).map(textOf)
    expect(flagsOf('TRADE_STATUS')).toContain('Constant')
    expect(flagsOf('PAR_TIMESTAMP')).toContain('Function')
    expect(flagsOf('END_DATE')).toEqual(expect.arrayContaining(['Not persisted', 'Inferred']))
    expect(flagsOf('FDK_MT')).toEqual([])

    expect(rowOf('END_DATE').querySelector('.badge.kind-not_persisted')?.textContent).toBe('Not persisted')
    expect(rowOf('PAR_TIMESTAMP').querySelector('.badge.kind-function')?.textContent).toBe('Function')
  })

  it('counts a direct mapping as one hop', async () => {
    await openTable('PAR_GFRS_CLO_TRADES')
    const row = rowOf('OFR_ACCEPTANCE_DATE')
    expect(textOf(within(row).getByRole('button', { name: 'Paths of OFR_ACCEPTANCE_DATE' }))).toContain('1 path · 1 hop')
    expect(textOf(within(row).getByRole('button', { name: 'Ultimate sources of OFR_ACCEPTANCE_DATE' }))).toContain('1 source')
  })

  it('expands and collapses everything at once', async () => {
    const { user, table } = await openTable('CM_PAR_LOAN_TRADES')
    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(within(table).getAllByRole('list', { name: /^Paths of/ })).toHaveLength(26)
    expect(within(table).getAllByRole('list', { name: /^Ultimate sources of/ })).toHaveLength(26)
    await user.click(screen.getByRole('button', { name: 'Collapse all' }))
    expect(within(table).queryAllByRole('list', { name: /^Paths of/ })).toHaveLength(0)
    expect(within(table).queryAllByRole('list', { name: /^Ultimate sources of/ })).toHaveLength(0)
  })

  it('filters columns by name and says how many are shown', async () => {
    const { user, table } = await openTable('CM_PAR_LOAN_TRADES')
    await user.type(screen.getByLabelText('Filter columns'), 'date')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.length).toBeGreaterThan(1)
    expect(rows.length).toBeLessThan(26)
    expect(rows.every((r) => textOf(r.querySelector('th')).toLowerCase().includes('date'))).toBe(true)
    expect(document.body.textContent).toContain(`Showing ${rows.length} of 26 columns`)

    await user.clear(screen.getByLabelText('Filter columns'))
    await user.type(screen.getByLabelText('Filter columns'), 'zzz')
    expect(await screen.findByText('No column matches the filter.')).toBeTruthy()
  })

  it('sorts by hops and by number of sources', async () => {
    const objectId = await ids('CM_PAR_LOAN_TRADES')
    const summary = await realClient().tableSummary('SP_CLO', objectId)
    const order = (key: (c: SummaryColumn) => number) =>
      [...summary.columns].sort((a, b) => key(b) - key(a) || a.column_name.localeCompare(b.column_name)).map((c) => c.column_name)
    const { user, table } = await openTable('CM_PAR_LOAN_TRADES')
    const shown = () => within(table).getAllByRole('row').slice(1).map((r) => textOf(r.querySelector('th button')))

    await user.selectOptions(screen.getByLabelText('Sort by'), 'hops')
    expect(shown()).toEqual(order((c) => c.hops_max ?? -1))
    await user.selectOptions(screen.getByLabelText('Sort by'), 'sources')
    expect(shown()).toEqual(order((c) => c.source_count))
    await user.selectOptions(screen.getByLabelText('Sort by'), 'name')
    expect(shown()).toEqual(summary.columns.map((c) => c.column_name))
  })

  it('shows exactly the numbers the API returns for every column', async () => {
    const objectId = await ids('CM_PAR_LOAN_TRADES')
    const summary = await realClient().tableSummary('SP_CLO', objectId)
    await openTable('CM_PAR_LOAN_TRADES')
    for (const column of summary.columns) {
      const row = rowOf(column.column_name)
      const hops = column.hops_min === column.hops_max ? `${column.hops_min} ${column.hops_min === 1 ? 'hop' : 'hops'}` : `${column.hops_min}–${column.hops_max} hops`
      const paths = `${column.source_count} ${column.source_count === 1 ? 'path' : 'paths'} · ${hops}`
      expect(textOf(within(row).getByRole('button', { name: `Paths of ${column.column_name}` }))).toContain(paths)
      expect(textOf(within(row).getByRole('button', { name: `Ultimate sources of ${column.column_name}` }))).toContain(
        `${column.source_count} ${column.source_count === 1 ? 'source' : 'sources'}`,
      )
    }
  })
})

describeReal('moving between the summary and the walkthrough', () => {
  async function openFdkMt() {
    const { user, objectId } = await openTable('CM_PAR_LOAN_TRADES')
    const summary = await realClient().tableSummary('SP_CLO', objectId)
    const column = summary.columns.find((c) => c.column_name === 'FDK_MT')!
    await user.click(screen.getByRole('button', { name: 'FDK_MT', exact: true }))
    await screen.findByRole('region', { name: 'Lineage session' })
    return { user, objectId, columnId: column.column_id }
  }

  it('opens the walkthrough with the table and column already chosen', async () => {
    const { objectId, columnId } = await openFdkMt()
    expect(window.location.hash).toBe(`#/lineage/SP_CLO/${objectId}/${columnId}`)
    await waitFor(() => expect((screen.getByLabelText('Project') as HTMLSelectElement).value).toBe('SP_CLO'))
    await waitFor(() => expect((screen.getByLabelText('Target Object') as HTMLSelectElement).value).toBe(objectId))
    await waitFor(() => expect((screen.getByLabelText('Target Column') as HTMLSelectElement).value).toBe(columnId))
    const target = screen.getByRole('region', { name: 'Target' })
    await waitFor(() => expect(textOf(target)).toContain('FDK_MT'))
    expect(textOf(target)).toContain('CM_PAR_LOAN_TRADES')
    const choices = screen.getByRole('region', { name: 'Upstream choices' })
    await waitFor(() => expect(within(within(choices).getByRole('list', { name: 'Upstream mappings' })).getAllByRole('listitem')).toHaveLength(1))
  })

  it('goes back to the same table from the walkthrough', async () => {
    const { user, objectId } = await openFdkMt()
    const link = screen.getByRole('link', { name: '← Back to summary' })
    expect(link.getAttribute('href')).toBe(`#/summary/SP_CLO/${objectId}`)
    await user.click(link)
    expect(await screen.findByRole('table')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'CM_PAR_LOAN_TRADES' })).toBeTruthy()
  })

  it('supports the browser Back button', async () => {
    await openFdkMt()
    window.history.back()
    expect(await screen.findByRole('table')).toBeTruthy()
    expect(window.location.hash).toMatch(/^#\/summary\/SP_CLO\//)
  })

  it('keeps the address in step with the selectors without restarting the walk', async () => {
    const { user, objectId } = await openFdkMt()
    const choices = screen.getByRole('region', { name: 'Upstream choices' })
    await waitFor(() => expect(within(choices).getAllByRole('listitem').length).toBeGreaterThan(0))
    const summary = await realClient().tableSummary('SP_CLO', objectId)
    const mde = summary.columns.find((c) => c.column_name === 'MDE_CODE')!

    await user.selectOptions(screen.getByLabelText('Target Column'), 'MDE_CODE')
    await waitFor(() => expect(window.location.hash).toBe(`#/lineage/SP_CLO/${objectId}/${mde.column_id}`))
    await waitFor(() => expect(textOf(screen.getByRole('region', { name: 'Target' }))).toContain('MDE_CODE'))
  })

  it('opens a shared address straight into the walkthrough', async () => {
    const objectId = await ids('AR_PAR_LOAN_EVENTS')
    const summary = await realClient().tableSummary('SP_CLO', objectId)
    const column = summary.columns.find((c) => c.column_name === 'MDE_CODE')!
    show(realClient(), `#/lineage/SP_CLO/${objectId}/${column.column_id}`)
    await screen.findByRole('region', { name: 'Lineage session' })
    expect(textOf(screen.getByRole('region', { name: 'Target' }))).toContain('MDE_CODE')
    await waitFor(() => expect((screen.getByLabelText('Target Column') as HTMLSelectElement).value).toBe(column.column_id))
  })

  it('explains an address that no longer matches the data', async () => {
    show(realClient(), '#/lineage/SP_CLO/OBJ_nope/COL_nope')
    await waitFor(() =>
      expect(screen.getAllByRole('alert').map(textOf).join(' ')).toContain('not in the current lineage data'),
    )
  })

  it('has navigation between the two pages', async () => {
    const user = show(realClient(), '#/summary')
    const nav = screen.getByRole('navigation', { name: 'Pages' })
    expect(within(nav).getByRole('link', { name: 'Summary' }).getAttribute('aria-current')).toBe('page')
    await user.click(within(nav).getByRole('link', { name: 'Walkthrough' }))
    expect(await screen.findByLabelText('Target Object')).toBeTruthy()
    expect(within(nav).getByRole('link', { name: 'Walkthrough' }).getAttribute('aria-current')).toBe('page')
    await user.click(within(nav).getByRole('link', { name: 'Summary' }))
    expect(await screen.findByLabelText('Search target tables')).toBeTruthy()
  })
})

describe('summary page with a scripted client', () => {
  const column = (overrides: Partial<SummaryColumn>): SummaryColumn => ({
    column_id: 'c', column_name: 'C', has_lineage: true, source_count: 1, hops_min: 1, hops_max: 1,
    flags: { constant: false, function: false, not_persisted: false, case_branches: false, inferred: false },
    sources: [{
      terminal_id: 't', object_name: 'SRC', column_name: 'S', object_type: 'DataObject', kind: 'column',
      condition: null, result_expression: null, leaf_relation_types: ['EXPLICIT_INATTR'], hops_min: 1, hops_max: 1,
      route_count: 1, route: [{ endpoint: 'SRC.S', relation_type: 'EXPLICIT_INATTR', component_name: 'Comp' }],
    }],
    ...overrides,
  })
  const object = { object_id: 'o1', object_name: 'ORDERS', source_project: 'A', business_processes: [], column_count: 2 }
  const summary: TableSummary = {
    object,
    totals: { columns: 2, with_lineage: 1 },
    columns: [
      column({ column_id: 'a', column_name: 'ALL_GOOD' }),
      column({
        column_id: 'b', column_name: 'NO_LINEAGE', has_lineage: false, source_count: 0, hops_min: null, hops_max: null, sources: [],
      }),
    ],
  }
  const client = (projects = [{ project_name: 'A' }]): ApiClient => ({
    projects: async () => projects,
    targets: async () => [object],
    columns: async () => [],
    searchTargets: async () => [object],
    tableSummary: async () => summary,
    rootChoices: async () => ({ choices: [] }),
    upstream: async () => ({ choices: [] }),
    remainingDepth: async () => { throw new Error('unused') },
    stepDetail: async () => { throw new Error('unused') },
    ultimateSources: async (t) => ({ project: t.project, object_id: t.objectId, column_id: t.columnId, step_id: null, terminal_sources: [] }),
  })

  it('lists a column without lineage and marks it', async () => {
    show(client(), '#/summary/A/o1')
    const table = await screen.findByRole('table')
    expect(document.body.textContent).toContain('2 columns · 1 with lineage')
    const row = within(table).getByRole('button', { name: 'NO_LINEAGE' }).closest('tr')!
    expect(textOf(row)).toContain('No lineage')
    expect(textOf(row)).toContain('No lineage found')
    expect(textOf(row)).toContain('No sources')
    expect(within(row).queryByRole('button', { name: /^Paths of/ })).toBeNull()
    expect(within(table).getByRole('button', { name: 'Paths of ALL_GOOD' })).toBeTruthy()
  })

  it('asks for a project first when there are several', async () => {
    const user = show(client([{ project_name: 'A' }, { project_name: 'B' }]), '#/summary')
    const project = (await screen.findByLabelText('Project')) as HTMLSelectElement
    expect(screen.queryByLabelText('Search target tables')).toBeNull()
    await user.selectOptions(project, 'B')
    expect(await screen.findByLabelText('Search target tables')).toBeTruthy()
    expect(window.location.hash).toBe('#/summary/B')
  })
})

describeReal('ultimate source details on the summary page', () => {
  it('opens the detail drawer from a source row', async () => {
    const { user } = await openTable('AR_PAR_LOAN_EVENTS')
    const row = rowOf('MDE_CODE')
    const details = within(row).getAllByRole('button', { name: /^Details for / })[0]
    await user.click(details)
    const drawer = await screen.findByRole('dialog')
    expect(drawer.textContent).toContain('Mapping')
    await user.keyboard('{Escape}')
  })
})
