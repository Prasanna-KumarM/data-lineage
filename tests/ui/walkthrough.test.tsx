import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../ui/src/App'
import type { ApiClient } from '../../ui/src/api/client'
import type { Choice, TerminalSource } from '../../ui/src/api/types'
import { describeReal, realClient } from './helpers'

const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement
const optionTexts = (el: HTMLSelectElement) => Array.from(el.options).map((o) => o.textContent)

const cardsIn = (scope: HTMLElement) =>
  within(scope).queryAllByRole('listitem').map((li) => within(li).getByRole('button'))
const cardTitles = (scope: HTMLElement) => cardsIn(scope).map((c) => c.querySelector('.card-title')?.textContent)
const pressed = (card: HTMLElement) => card.getAttribute('aria-pressed') === 'true'
const sourceNames = (scope: HTMLElement) =>
  within(scope).queryAllByRole('listitem').map((li) => li.querySelector('.source-name')?.textContent)

async function openApp(client: ApiClient, objectName: string, columnName: string) {
  const user = userEvent.setup()
  render(<App client={client} />)
  await waitFor(() => expect(optionTexts(select('Target Object')).length).toBeGreaterThan(1))
  await user.selectOptions(select('Target Object'), objectName)
  await waitFor(() => expect(optionTexts(select('Target Column')).length).toBeGreaterThan(1))
  await user.selectOptions(select('Target Column'), columnName)
  const workspace = await screen.findByRole('region', { name: 'Lineage session' })
  const choices = within(workspace).getByRole('region', { name: 'Upstream choices' })
  await waitFor(() => expect(cardsIn(choices).length).toBeGreaterThan(0))
  return {
    user,
    workspace,
    choices,
    target: within(workspace).getByRole('region', { name: 'Target' }),
    sources: within(workspace).getByRole('region', { name: 'Ultimate sources' }),
    next: () => within(choices).getByRole('button', { name: 'Next' }) as HTMLButtonElement,
    back: () => within(choices).getByRole('button', { name: 'Back' }) as HTMLButtonElement,
  }
}

describeReal('hop-by-hop walkthrough on the real SP_CLO lineage', () => {
  it('walks the four-hop FDK_MT chain forward and back without ever showing sibling routes', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices, target, sources } = app
    const targetBefore = target.textContent

    // Hop 1: two same-endpoint steps; only one continues.
    expect(app.back().disabled).toBe(true)
    expect(app.next().disabled).toBe(true)
    expect(choices.textContent).toContain('Hop 1 · upstream of CM_PAR_LOAN_TRADES.FDK_MT')
    const root = cardsIn(choices)
    expect(root).toHaveLength(2)
    const chain = root.find((c) => c.textContent?.includes('1 upstream choice'))!
    await user.click(chain)
    expect(app.next().disabled).toBe(false)
    await user.click(app.next())

    // Hop 2: the sibling root route is gone.
    await waitFor(() => expect(choices.textContent).toContain('Hop 2 · upstream of CM_CLO_OFFER.e_fdk_mt'))
    await waitFor(() => expect(cardTitles(choices)).toEqual(['FSD_FO_DESKS.FDK_MT']))
    expect(app.back().disabled).toBe(false)
    expect(app.next().disabled).toBe(true)
    await waitFor(() => expect(sourceNames(sources)).toHaveLength(3))
    expect(target.textContent).toBe(targetBefore)

    await user.click(cardsIn(choices)[0])
    await user.click(app.next())

    // Hop 3: the enrichment lookup.
    await waitFor(() => expect(choices.textContent).toContain('Hop 3 · upstream of FSD_FO_DESKS.FDK_MT'))
    await waitFor(() => expect(cardTitles(choices)).toEqual(['CM_CLO_OFFER.e_bok_code']))
    expect(cardsIn(choices)[0].textContent).toContain('Lookup')
    await user.click(cardsIn(choices)[0])
    await user.click(app.next())

    // Hop 4: three sibling terminal columns.
    await waitFor(() => expect(choices.textContent).toContain('Hop 4 · upstream of CM_CLO_OFFER.e_bok_code'))
    await waitFor(() => expect(cardTitles(choices)).toHaveLength(3))
    expect(cardTitles(choices)).toEqual([
      'CM_CLO_OFFER.OFR_HTCS_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTC_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTS_BOOK_CODE',
    ])
    expect(app.next().disabled).toBe(true)
    await user.click(cardsIn(choices)[1])
    expect(app.next().disabled).toBe(true)
    await waitFor(() => expect(sourceNames(sources)).toEqual(['CM_CLO_OFFER.OFR_HTC_BOOK_CODE']))

    // Back restores each earlier level with its selection.
    await user.click(app.back())
    await waitFor(() => expect(choices.textContent).toContain('Hop 3'))
    expect(cardTitles(choices)).toEqual(['CM_CLO_OFFER.e_bok_code'])
    expect(pressed(cardsIn(choices)[0])).toBe(true)
    await user.click(app.back())
    expect(cardTitles(choices)).toEqual(['FSD_FO_DESKS.FDK_MT'])
    expect(pressed(cardsIn(choices)[0])).toBe(true)
    await user.click(app.back())

    expect(choices.textContent).toContain('Hop 1')
    const restored = cardsIn(choices)
    expect(restored).toHaveLength(2)
    expect(pressed(restored.find((c) => c.textContent?.includes('1 upstream choice'))!)).toBe(true)
    expect(pressed(restored.find((c) => c.textContent?.includes('nothing further upstream'))!)).toBe(false)
    await waitFor(() => expect(sourceNames(sources)).toHaveLength(3))
    expect(app.back().disabled).toBe(true)
    expect(target.textContent).toBe(targetBefore)
  })

  it('does not allow Next on a terminal choice', async () => {
    const { user, choices, next } = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const leaf = cardsIn(choices).find((c) => c.textContent?.includes('nothing further upstream'))!
    await user.click(leaf)
    expect(pressed(leaf)).toBe(true)
    expect(next().disabled).toBe(true)
    expect(next().title).toBe('Nothing further upstream')
    expect(cardsIn(choices)).toHaveLength(2)
  })

  it('follows one branch of a multi-choice target', async () => {
    const { user, choices, sources, next } = await openApp(
      realClient(),
      'PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)',
      'CONTRACT_ID',
    )
    expect(cardTitles(choices)).toEqual([
      'AR_CLO_ACCOUNTING_EVENTS.AEF_EVENT_CODE',
      'AR_CLO_ACCOUNTING_EVENTS.AEF_OFFER_ID',
      'AR_CLO_ACCOUNTING_EVENTS.e_contract_id',
    ])
    const branching = cardsIn(choices)[2]
    await user.click(branching)
    await user.click(next())
    await waitFor(() => expect(choices.textContent).toContain('Hop 2 · upstream of AR_CLO_ACCOUNTING_EVENTS.e_contract_id'))
    await waitFor(() => expect(cardsIn(choices).length).toBe(1))
    expect(cardTitles(choices)).not.toContain('AR_CLO_ACCOUNTING_EVENTS.AEF_EVENT_CODE')
    await waitFor(() => expect(sourceNames(sources).length).toBeGreaterThan(0))
  })

  it('walking into a CASE branch keeps its condition on the source', async () => {
    const { user, choices, sources, next } = await openApp(realClient(), 'AR_PAR_LOAN_EVENTS', 'PDT_CODE')
    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await waitFor(() => expect(cardsIn(choices)).toHaveLength(2))
    await user.click(cardsIn(choices)[1])
    await waitFor(() => expect(sourceNames(sources)).toHaveLength(1))
    expect(sources.querySelector('.source-condition')?.textContent).toMatch(/^when /)
  })

  it('choosing another target throws the navigation away', async () => {
    const { user, choices, next } = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    await user.click(next())
    await waitFor(() => expect(choices.textContent).toContain('Hop 2'))

    await user.selectOptions(select('Target Object'), 'AR_PAR_LOAN_EVENTS')
    await waitFor(() => expect(optionTexts(select('Target Column')).length).toBeGreaterThan(1))
    await user.selectOptions(select('Target Column'), 'MDE_CODE')
    const workspace = await screen.findByRole('region', { name: 'Lineage session' })
    const fresh = within(workspace).getByRole('region', { name: 'Upstream choices' })
    await waitFor(() => expect(fresh.textContent).toContain('Hop 1 · upstream of AR_PAR_LOAN_EVENTS.MDE_CODE'))
    expect(within(fresh).getByRole('button', { name: 'Back' }).hasAttribute('disabled')).toBe(true)
    expect(cardsIn(fresh).every((c) => !pressed(c))).toBe(true)
  })
})

// The approved example: p1 -> p1.1, p1.2; p2 -> p2.1; p3 -> p3.1. A scripted client lets us count calls.
describe('single-branch navigation on the p1/p2/p3 example', () => {
  const children: Record<string, string[]> = {
    root: ['p1', 'p2', 'p3'],
    p1: ['p1.1', 'p1.2'],
    'p1.2': ['p1.2.1'],
    p2: ['p2.1'],
    'p2.1': ['p2.1.1', 'p2.1.2', 'p2.1.3'],
    p3: ['p3.1'],
  }

  const choiceFor = (id: string): Choice => ({
    step_id: id, relation_id: `r-${id}`, relation_type: 'EXPLICIT_INATTR',
    source_object_id: 'o', source_column_id: `c-${id}`, source_object_name: 'SRC', source_column_name: id,
    target_object_id: 'o', target_column_id: 'c', target_object_name: 'TGT', target_column_name: 'T',
    component_id: null, component_name: null, component_type: null,
    business_process_id: null, business_process_name: null,
    confidence_class: 'Explicit', confidence_reason_code: null,
    traversal_path: null, driving_expression: null, result_expression: null, expression_id: null,
    lineage_level: 0, is_terminal: !children[id], has_more_upstream: Boolean(children[id]),
    upstream_choice_count: children[id]?.length ?? 0,
  })

  const leaves = (id: string): string[] => (children[id] ? children[id].flatMap(leaves) : [id])
  const terminal = (id: string): TerminalSource => ({
    terminal_id: id, object_id: 'o', column_id: `c-${id}`, object_name: 'SRC', column_name: id,
    object_type: 'DataObject', condition: null, result_expression: null, leaf_relation_types: ['EXPLICIT_INATTR'],
  })

  function scripted() {
    const upstreamCalls: string[] = []
    const client: ApiClient = {
      projects: async () => [{ project_name: 'A' }],
      targets: async () => [
        { object_id: 'o1', object_name: 'ORDERS', source_project: 'A', business_processes: [], column_count: 1 },
      ],
      columns: async () => [{ column_id: 'c1', column_name: 'ID', step_count: 3 }],
      rootChoices: async () => ({ choices: children.root.map(choiceFor) }),
      upstream: async (stepId) => {
        upstreamCalls.push(stepId)
        return { choices: (children[stepId] ?? []).map(choiceFor) }
      },
      ultimateSources: async (t, _signal, stepId) => ({
        project: t.project, object_id: t.objectId, column_id: t.columnId, step_id: stepId ?? null,
        terminal_sources: (stepId ? leaves(stepId) : children.root.flatMap(leaves)).map(terminal),
      }),
    }
    return { client, upstreamCalls }
  }

  it('shows p1, p2, p3 first; then only p1.1, p1.2; then only p1.2.1', async () => {
    const { client, upstreamCalls } = scripted()
    const { user, choices, sources, next } = await openApp(client, 'ORDERS', 'ID')
    expect(cardTitles(choices)).toEqual(['SRC.p1', 'SRC.p2', 'SRC.p3'])
    await waitFor(() => expect(sourceNames(sources)).toHaveLength(6))

    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await waitFor(() => expect(cardTitles(choices)).toEqual(['SRC.p1.1', 'SRC.p1.2']))

    await user.click(cardsIn(choices)[1])
    await waitFor(() => expect(sourceNames(sources)).toEqual(['SRC.p1.2.1']))
    await user.click(next())
    await waitFor(() => expect(cardTitles(choices)).toEqual(['SRC.p1.2.1']))
    expect(next().disabled).toBe(true)

    // Sibling branches were never fetched.
    expect(upstreamCalls).toEqual(['p1', 'p1.2'])
  })

  it('Back restores the exact previous choices and the selected relation without refetching', async () => {
    const { client, upstreamCalls } = scripted()
    const { user, choices, next, back } = await openApp(client, 'ORDERS', 'ID')
    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await waitFor(() => expect(cardTitles(choices)).toEqual(['SRC.p1.1', 'SRC.p1.2']))
    await user.click(cardsIn(choices)[1])
    await user.click(next())
    await waitFor(() => expect(cardTitles(choices)).toEqual(['SRC.p1.2.1']))

    await user.click(back())
    expect(cardTitles(choices)).toEqual(['SRC.p1.1', 'SRC.p1.2'])
    expect(cardsIn(choices).map(pressed)).toEqual([false, true])

    await user.click(back())
    expect(cardTitles(choices)).toEqual(['SRC.p1', 'SRC.p2', 'SRC.p3'])
    expect(cardsIn(choices).map(pressed)).toEqual([true, false, false])
    expect(upstreamCalls).toEqual(['p1', 'p1.2'])
  })

  it('choosing a different branch after Back follows that branch only', async () => {
    const { client, upstreamCalls } = scripted()
    const { user, choices, next, back } = await openApp(client, 'ORDERS', 'ID')
    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await waitFor(() => expect(cardTitles(choices)).toEqual(['SRC.p1.1', 'SRC.p1.2']))
    await user.click(back())
    await user.click(cardsIn(choices)[1])
    await user.click(next())
    await waitFor(() => expect(cardTitles(choices)).toEqual(['SRC.p2.1']))
    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await waitFor(() => expect(cardTitles(choices)).toEqual(['SRC.p2.1.1', 'SRC.p2.1.2', 'SRC.p2.1.3']))
    expect(upstreamCalls).toEqual(['p1', 'p2', 'p2.1'])
  })
})
