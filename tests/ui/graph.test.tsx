import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import type { ApiClient } from '../../src/ui/src/api/client'
import { toFlow } from '../../src/ui/src/components/LineageGraph'
import { layoutGraph } from '../../src/ui/src/components/graphLayout'
import { describeReal, realClient } from './helpers'

function show(client: ApiClient, hash: string) {
  cleanup()
  window.history.replaceState(null, '', hash)
  const user = userEvent.setup()
  render(<App client={client} />)
  return user
}

async function openTable(objectName: string, client: ApiClient = realClient()) {
  const objects = await realClient().targets('SP_CLO')
  const object = objects.find((o) => o.object_name === objectName)!
  const user = show(client, `#/summary/SP_CLO/${object.object_id}`)
  await screen.findByRole('table')
  return { user, object }
}

const textOf = (el: Element | null) => el?.textContent ?? ''
const nodesOf = (dialog: HTMLElement, role: string) => within(dialog).getAllByTestId(`graph-node-${role}`)

describeReal('graph view of a column on the real SP_CLO lineage', () => {
  it('offers a Graph button for every column that has lineage', async () => {
    await openTable('CM_PAR_LOAN_TRADES')
    expect(screen.getAllByRole('button', { name: /^Graph of / })).toHaveLength(26)
    expect(screen.getByRole('button', { name: 'Graph of FDK_MT' })).toBeTruthy()
  })

  it('has no Graph button for a column without lineage', async () => {
    const real = realClient()
    const client: ApiClient = {
      ...real,
      tableSummary: async (project, objectId, signal) => {
        const summary = await real.tableSummary(project, objectId, signal)
        const [first, ...rest] = summary.columns
        return { ...summary, columns: [{ ...first, has_lineage: false, sources: [], source_count: 0, hops_min: null, hops_max: null }, ...rest] }
      },
    }
    const { object } = await openTable('CM_PAR_LOAN_TRADES', client)
    const summary = await client.tableSummary('SP_CLO', object.object_id)
    expect(screen.queryByRole('button', { name: `Graph of ${summary.columns[0].column_name}` })).toBeNull()
    expect(screen.getAllByRole('button', { name: /^Graph of / })).toHaveLength(25)
  })

  it('opens a window with the whole graph: target, intermediate steps and every ultimate source', async () => {
    const { user } = await openTable('CM_PAR_LOAN_TRADES')
    await user.click(screen.getByRole('button', { name: 'Graph of FDK_MT' }))
    const dialog = await screen.findByRole('dialog', { name: 'Lineage graph of FDK_MT' })
    await within(dialog).findAllByTestId('graph-node-target')
    expect(textOf(dialog)).toContain('CM_PAR_LOAN_TRADES.FDK_MT')
    expect(textOf(dialog)).toContain('3 ultimate sources · up to 4 hops · 6 mappings')
    expect(nodesOf(dialog, 'target')).toHaveLength(1)
    expect(nodesOf(dialog, 'intermediate')).toHaveLength(3)
    const sources = nodesOf(dialog, 'source')
    expect(nodesOf(dialog, 'target')[0].querySelector('.react-flow__handle-right')).not.toBeNull()
    expect(sources[0].querySelector('.react-flow__handle-left')).not.toBeNull()
    expect(sources.map((s) => s.querySelector('.graph-node-name')?.textContent)).toEqual([
      'CM_CLO_OFFER.OFR_HTCS_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTC_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTS_BOOK_CODE',
    ])
    expect(textOf(sources[0])).toContain('Column')
    expect(textOf(sources[0])).toContain('4 hops')
    expect(within(dialog).getByRole('button', { name: 'Fit to screen' })).toBeTruthy()
  })

  it('shows each CASE branch to a constant as its own source with its condition', async () => {
    const { user } = await openTable('AR_PAR_LOAN_EVENTS')
    await user.click(screen.getByRole('button', { name: 'Graph of PDT_CODE' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findAllByTestId('graph-node-target')
    const sources = nodesOf(dialog, 'source')
    expect(sources).toHaveLength(2)
    expect(sources.map(textOf).join('|')).toContain('EXPR AEF_EVENT_CODE=="E011"')
    expect(sources.map(textOf).join('|')).toContain('EXPR ELSE')
    expect(sources.every((s) => textOf(s).includes('Constant'))).toBe(true)
  })

  it('closes with the Close button, Escape and a click outside, and gives focus back', async () => {
    const { user } = await openTable('CM_PAR_LOAN_TRADES')
    const opener = screen.getByRole('button', { name: 'Graph of FDK_MT' })

    await user.click(opener)
    await screen.findByRole('dialog')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }))
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(opener)

    await user.click(opener)
    await screen.findByRole('dialog')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()

    await user.click(opener)
    const dialog = await screen.findByRole('dialog')
    await user.click(dialog.parentElement!)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('does not leave the window open when another table is chosen', async () => {
    const { user } = await openTable('CM_PAR_LOAN_TRADES')
    await user.click(screen.getByRole('button', { name: 'Graph of FDK_MT' }))
    await screen.findByRole('dialog')
    window.location.hash = '#/summary/SP_CLO'
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('reports a failed load and recovers on Retry', async () => {
    let fail = true
    const flaky: typeof fetch = (input, init) =>
      fail && String(input).includes('/lineage/graph')
        ? Promise.resolve(new Response(JSON.stringify({ error: { code: 'DATABASE_UNAVAILABLE', message: 'The lineage database is unavailable.' } }), { status: 503 }))
        : fetch(input, init)
    const { user } = await openTable('CM_PAR_LOAN_TRADES', realClient({ fetchImpl: flaky }))
    await user.click(screen.getByRole('button', { name: 'Graph of FDK_MT' }))
    const dialog = await screen.findByRole('dialog')
    const alert = await within(dialog).findByRole('alert')
    expect(alert.textContent).toContain('The lineage database is unavailable.')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect((await within(dialog).findAllByTestId('graph-node-target')).length).toBe(1)
  })

  it('lays the graph out left to right by hop without overlapping nodes', async () => {
    const client = realClient()
    const objects = await client.targets('SP_CLO')
    const object = objects.find((o) => o.object_name === 'CM_PAR_LOAN_TRADES')!
    const columns = await client.columns('SP_CLO', object.object_id)
    for (const column of columns) {
      const graph = await client.columnGraph({ project: 'SP_CLO', objectId: object.object_id, columnId: column.column_id })
      if (!graph.has_lineage) continue
      const placed = layoutGraph(graph)
      const at = new Map(placed.map((p) => [p.id, p]))
      for (const edge of graph.edges) {
        expect(at.get(edge.to_node)!.x, column.column_name).toBeGreaterThan(at.get(edge.from_node)!.x)
      }
      for (const a of placed) {
        for (const b of placed) {
          if (a.id >= b.id) continue
          const apart = a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y
          expect(apart, `${column.column_name}: ${a.id} / ${b.id}`).toBe(true)
        }
      }
    }
  })

  it('draws arrows from each source-side node back toward its target-side node', async () => {
    const client = realClient()
    const objects = await client.targets('SP_CLO')
    const object = objects.find((o) => o.object_name === 'CM_PAR_LOAN_TRADES')!
    const column = (await client.columns('SP_CLO', object.object_id)).find((c) => c.column_name === 'FDK_MT')!
    const graph = await client.columnGraph({ project: 'SP_CLO', objectId: object.object_id, columnId: column.column_id })
    const flow = toFlow(graph, null)
    const positions = new Map(layoutGraph(graph).map((node) => [node.id, node]))
    const storedEdges = new Map(graph.edges.map((edge) => [edge.edge_id, edge]))

    for (const edge of flow.edges) {
      const stored = storedEdges.get(edge.id)!
      expect(edge.source).toBe(stored.to_node)
      expect(edge.target).toBe(stored.from_node)
      expect(positions.get(edge.source)!.x).toBeGreaterThan(positions.get(edge.target)!.x)
    }
  })
})
