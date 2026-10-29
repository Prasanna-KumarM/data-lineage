import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import type { ApiClient } from '../../src/ui/src/api/client'
import { describeReal, realClient } from './helpers'

const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement

// The test server exposes only SP_CLO, so the continuation points back into it.
async function openWithTrack() {
  const real = realClient()
  const cloObject = (await real.targets('SP_CLO')).find((o) => o.object_name === 'CM_PAR_LOAN_TRADES')!
  const cloColumn = (await real.columns('SP_CLO', cloObject.object_id)).find((c) => c.column_name === 'FDK_MT')!
  const continuations: ApiClient['continuations'] = async (project, obj, col) =>
    obj === 'CM_CLO_OFFER' && (col === 'e_fdk_mt' || col === 'OFR_HTCS_BOOK_CODE')
      ? [{ project: 'SP_CLO', object_id: cloObject.object_id, column_id: cloColumn.column_id }]
      : []
  const client: ApiClient = {
    ...real,
    continuations,
    // The walkthrough binds the client per project; keep the override through the binding.
    forProject: (name) => ({ ...real.forProject!(name), continuations, forProject: real.forProject }),
  }
  cleanup()
  window.history.replaceState(null, '', '#/lineage')
  const user = userEvent.setup()
  render(<App client={client} />)
  await waitFor(() => expect(select('Target Object').options.length).toBeGreaterThan(1))
  await user.selectOptions(select('Target Object'), 'CM_PAR_LOAN_TRADES')
  await waitFor(() => expect(select('Target Column').options.length).toBeGreaterThan(1))
  await user.selectOptions(select('Target Column'), 'FDK_MT')
  return { user }
}

describeReal('continuing the walkthrough in another project', () => {
  it('offers Track on a card, loads that frame, and Back returns', async () => {
    const { user } = await openWithTrack()
    const workspace = await screen.findByRole('region', { name: 'Lineage session' })
    // The application badge always shows which project is on screen.
    expect(workspace.querySelector('.app-badge')?.textContent).toBe('SP_CLO')
    const choices = within(workspace).getByRole('region', { name: 'Upstream choices' })
    await within(choices).findByRole('list', { name: 'Upstream mappings' })
    // e_fdk_mt reaches the target through two mappings, so there are two cards.
    const track = (await within(choices).findAllByRole('button', { name: 'Track in SP_CLO →' }))[0]

    await user.click(track)
    expect((await screen.findByRole('note')).textContent).toContain('Tracking CM_PAR_LOAN_TRADES.FDK_MT in SP_CLO')
    const session2 = screen.getByRole('region', { name: 'Lineage session' })
    await within(session2).findByRole('list', { name: 'Upstream mappings' })
    expect(within(session2).getByText('CM_PAR_LOAN_TRADES')).toBeTruthy()
    expect(within(session2).getByText('FDK_MT')).toBeTruthy()

    const back = within(session2).getByRole('button', { name: /Back/ })
    expect((back as HTMLButtonElement).disabled).toBe(false)
    expect(back.textContent).toContain('CM_PAR_LOAN_TRADES.FDK_MT (SP_CLO)')
    await user.click(back)
    await waitFor(() => expect(screen.queryByRole('note')).toBeNull())
    const workspaceBack = screen.getByRole('region', { name: 'Lineage session' })
    await within(workspaceBack).findByRole('list', { name: 'Upstream mappings' })
  })

  it('offers a prominent Continue button next to the ultimate source', async () => {
    const { user } = await openWithTrack()
    const workspace = await screen.findByRole('region', { name: 'Lineage session' })
    const sources = within(workspace).getByRole('region', { name: 'Ultimate sources' })
    const cont = await within(sources).findByRole('button', { name: 'Continue in SP_CLO →' })
    await user.click(cont)
    expect((await screen.findByRole('note')).textContent).toContain('Tracking CM_PAR_LOAN_TRADES.FDK_MT in SP_CLO')
    const session2 = screen.getByRole('region', { name: 'Lineage session' })
    await within(session2).findByRole('list', { name: 'Upstream mappings' })
    expect(session2.querySelector('.app-badge')?.textContent).toBe('SP_CLO')
  })

  it('graph view: Track on the focused node and Back returns to the previous graph', async () => {
    const { user } = await openWithTrack()
    await user.click(screen.getByRole('button', { name: 'Graph view' }))
    const walk = await screen.findByRole('region', { name: 'Graph walkthrough' })
    await within(walk).findAllByTestId('walk-node-current')

    // Hop 1 splits into two mappings to the same node; pick the first, then step into it.
    await user.click((await within(walk).findAllByRole('button', { name: /e_fdk_mt/ }))[0])
    await user.click(within(walk).getByRole('button', { name: /Next/ }))
    expect(within(walk).getByText('Step 2')).toBeTruthy()

    await user.click(await within(walk).findByRole('button', { name: 'Track in SP_CLO →' }))
    expect((await screen.findByRole('note')).textContent).toContain('Tracking CM_PAR_LOAN_TRADES.FDK_MT in SP_CLO')
    const walk2 = await screen.findByRole('region', { name: 'Graph walkthrough' })
    await within(walk2).findAllByText('CM_PAR_LOAN_TRADES.FDK_MT')
    expect(within(walk2).getByText('Step 1')).toBeTruthy()

    await user.click(within(walk2).getByRole('button', { name: /Back/ }))
    await waitFor(() => expect(screen.queryByRole('note')).toBeNull())
  }, 30000)
})
