import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import type { ColumnGraph } from '../../src/ui/src/api/types'
import { initialWalk, stepBack, stepNext, viewOf, type WalkState } from '../../src/ui/src/state/graphWalk'
import { describeReal, realClient } from './helpers'

async function graphs(objectName: string) {
  const client = realClient()
  const object = (await client.targets('SP_CLO')).find((o) => o.object_name === objectName)!
  const columns = await client.columns('SP_CLO', object.object_id)
  const out: { column: string; graph: ColumnGraph }[] = []
  for (const column of columns) {
    const graph = await client.columnGraph({ project: 'SP_CLO', objectId: object.object_id, columnId: column.column_id })
    if (graph.has_lineage) out.push({ column: column.column_name, graph })
  }
  return { object, out }
}

describeReal('graph walkthrough state on the real SP_CLO lineage', () => {
  it('walks to an ultimate source and back to the target, choosing at every split', async () => {
    const { out } = await graphs('AR_PAR_LOAN_EVENTS')
    for (const { column, graph } of out) {
      let walk: WalkState = initialWalk
      let guard = 0
      for (;;) {
        const view = viewOf(graph, walk)
        if (view.upstream.length === 0) break
        if (view.upstream.length > 1) {
          expect(view.nextEdge, `${column}: a split needs a choice`).toBeNull()
          expect(stepNext(walk, view)).toBe(walk)
          walk = { ...walk, nextId: view.upstream[view.upstream.length - 1].edge_id }
        }
        walk = stepNext(walk, viewOf(graph, walk))
        expect(++guard).toBeLessThan(50)
      }
      expect(viewOf(graph, walk).current.role, column).toBe('source')
      while (walk.path.length) {
        const view = viewOf(graph, walk)
        if (view.downstream.length > 1) {
          expect(view.backNode, `${column}: a merge needs a choice`).toBeNull()
          walk = { ...walk, backId: view.via!.from_node }
        }
        walk = stepBack(graph, walk, viewOf(graph, walk))
      }
      expect(viewOf(graph, walk).current.role, column).toBe('target')
    }
  })

  it('goes back to a different node than the one walked when the user chooses it', async () => {
    const { out } = await graphs('CM_PAR_LOAN_TRADES')
    const merge = out.find(({ graph }) => graph.nodes.some((n) => new Set(graph.edges.filter((e) => e.to_node === n.node_id).map((e) => e.from_node)).size > 1))
    if (!merge) return
    const { graph } = merge
    const node = graph.nodes.find((n) => new Set(graph.edges.filter((e) => e.to_node === n.node_id).map((e) => e.from_node)).size > 1)!
    const walkTo = (via: string) => ({ ...initialWalk, path: [graph.edges.find((e) => e.to_node === via)!.edge_id] })
    const view = viewOf(graph, walkTo(node.node_id))
    const other = view.downstream.find((n) => n.node_id !== view.via!.from_node)!
    const back = stepBack(graph, { ...walkTo(node.node_id), backId: other.node_id }, viewOf(graph, { ...walkTo(node.node_id), backId: other.node_id }))
    expect(viewOf(graph, back).current.node_id).toBe(other.node_id)
  })
})

describeReal('graph walkthrough view', () => {
  it('shows the graph with one full-size block, and needs a choice at a split before Next', async () => {
    const { object, out } = await graphs('CM_PAR_LOAN_TRADES')
    const split = out.find(({ graph }) => graph.edges.filter((e) => e.from_node === graph.nodes.find((n) => n.role === 'target')!.node_id).length > 1)
    expect(split, 'expected a column whose target splits').toBeTruthy()

    cleanup()
    window.history.replaceState(null, '', '#/lineage')
    const user = userEvent.setup()
    render(<App client={realClient()} />)
    const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement
    await waitFor(() => expect(select('Target Object').options.length).toBeGreaterThan(1))
    await user.selectOptions(select('Target Object'), object.object_name)
    await waitFor(() => expect(select('Target Column').options.length).toBeGreaterThan(1))
    await user.selectOptions(select('Target Column'), split!.column)

    await user.click(await screen.findByRole('button', { name: 'Graph view' }))
    const walk = await screen.findByRole('region', { name: 'Graph walkthrough' })
    await within(walk).findAllByTestId('walk-node-current')
    expect(within(walk).getAllByTestId('walk-node-current')).toHaveLength(1)
    // The whole graph is drawn, with the target as the one enlarged block at the start.
    expect(walk.querySelectorAll('[data-testid^="walk-node-"]')).toHaveLength(split!.graph.nodes.length)
    expect(within(walk.querySelector('[data-testid="walk-node-current"]')!.closest('.graph-node') as HTMLElement).getByText('Target')).toBeTruthy()
    const next = within(walk).getByRole('button', { name: /Next/ }) as HTMLButtonElement
    const back = within(walk).getByRole('button', { name: /Back/ }) as HTMLButtonElement
    expect(next.disabled).toBe(true)
    expect(back.disabled).toBe(true)

    const choices = within(within(walk).getByRole('list', { name: 'Upstream mappings' })).getAllByRole('button')
    await user.click(choices[0])
    expect(next.disabled).toBe(false)
    await user.click(next)
    expect(within(walk).getByText('Step 2')).toBeTruthy()
    expect(within(walk).getAllByTestId('walk-node-current')).toHaveLength(1)
    expect(back.disabled).toBe(false)
    await user.click(back)
    expect(within(walk).getByText('Step 1')).toBeTruthy()

    await user.click(screen.getByRole('button', { name: 'List view' }))
    expect(await screen.findByRole('region', { name: 'Lineage session' })).toBeTruthy()
  })
})
