import { screen, waitFor, within } from '@testing-library/react'
import type { ApiClient } from '../../ui/src/api/client'
import type { StepDetail } from '../../ui/src/api/types'
import { advance, cardsIn, hopContext, openApp, pressed } from './appHelpers'
import { describeReal, realClient } from './helpers'

type App = Awaited<ReturnType<typeof openApp>>

const detailsButton = (card: HTMLElement) => card.closest('li')!.querySelector('button.card-details') as HTMLButtonElement
const dialog = () => screen.findByRole('dialog', { name: 'Mapping details' })
const textOf = (el: HTMLElement) => el.textContent ?? ''
const section = (drawer: HTMLElement, name: string) => within(drawer).getByRole('region', { name })
const cardWith = (cards: HTMLElement[], text: string) => cards.find((c) => textOf(c).includes(text))!

async function openDetails(app: App, card: HTMLElement) {
  await app.user.click(detailsButton(card))
  return dialog()
}

/** Walks PDT_CODE to the level with the two CASE branches that feed one constant. */
async function openPdtCodeBranches() {
  const app = await openApp(realClient(), 'AR_PAR_LOAN_EVENTS', 'PDT_CODE')
  await app.user.click(cardsIn(app.choices)[0])
  await advance(app, 2)
  return app
}

describeReal('mapping cards on the real SP_CLO lineage', () => {
  it('keeps technical identifiers off the default card', async () => {
    const { choices } = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    for (const card of cardsIn(choices)) {
      expect(textOf(card)).not.toMatch(/BLS_|MAP_|EXP_|OBJ_|COL_|CMP_/)
    }
  })

  it('shows each CASE branch as its own card with its condition and value', async () => {
    const { choices } = await openPdtCodeBranches()
    const cards = cardsIn(choices)
    expect(cards).toHaveLength(2)
    const [first, second] = cards
    expect(textOf(first)).toContain('WhenAEF_EVENT_CODE=="E011"')
    expect(textOf(first)).toContain('Value"OFFER"')
    expect(textOf(second)).toContain('WhenELSE')
    expect(textOf(second)).toContain('Value"OFFER"')
    expect(first.querySelector('.expr-tag.when')).not.toBeNull()
    expect(first.querySelector('.expr-tag.value')).not.toBeNull()
  })

  it('shows an expression root choice with its condition', async () => {
    const { choices } = await openApp(realClient(), 'PAR_UNPROCESSED_EVENTS (GP_SHARED · AR_CLO_EVENT_PROCESSING)', 'PAR_REASON')
    const conditions = cardsIn(choices).map((c) => c.querySelector('.expr-line:first-child code')?.textContent)
    expect(conditions.sort()).toEqual(['ELSE', 'IsNull(e_cou_country_code)', 'IsNull(e_pcr_code)', 'IsNull(e_product_group)'])
  })

  it('makes a constant, a function and a not-persisted mapping visibly different', async () => {
    const constant = cardsIn((await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'TRADE_STATUS')).choices)[0]
    expect(textOf(constant)).toContain('CONSTANT."A"')
    expect(textOf(constant)).toContain('Constant')
    expect(constant.className).toContain('tone-constant')
    document.body.innerHTML = ''

    const fn = cardsIn((await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'PAR_TIMESTAMP')).choices)[0]
    expect(textOf(fn)).toContain('FUNCTION.Today( )')
    expect(textOf(fn)).toContain('Function')
    expect(fn.className).toContain('tone-function')
    document.body.innerHTML = ''

    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'END_DATE')
    await app.user.click(cardWith(cardsIn(app.choices), '1 upstream choice'))
    await advance(app, 2)
    const notPersisted = cardsIn(app.choices)[0]
    expect(textOf(notPersisted)).toContain('NOT_PERSISTED.NONE')
    expect(textOf(notPersisted)).toContain('Not persisted')
    expect(notPersisted.className).toContain('tone-not-persisted')
    expect(new Set([constant.className, fn.className, notPersisted.className].map((c) => c.match(/tone-[\w-]+/)![0])).size).toBe(3)
  })
})

describeReal('relation detail drawer on the real SP_CLO lineage', () => {
  it('opens from a card, moves focus into the drawer, and shows the mapping', async () => {
    const app = await openPdtCodeBranches()
    const card = cardsIn(app.choices)[0]
    const drawer = await openDetails(app, card)
    await within(drawer).findByRole('region', { name: 'Mapping' })
    expect(document.activeElement).toBe(within(drawer).getByRole('button', { name: 'Close details' }))
    const mapping = section(drawer, 'Mapping')
    expect(textOf(mapping)).toContain('"OFFER"."OFFER"')
    expect(textOf(mapping)).toContain('AR_CLO_ACCOUNTING_EVENTS.e_product_code')
    expect(textOf(mapping)).toContain('Expression')
    expect(textOf(mapping)).toContain('AR_CLO_Enrichment')
    expect(textOf(mapping)).toContain('AR_CLO_EVENT_PROCESSING')
    expect(detailsButton(card).getAttribute('aria-expanded')).toBe('true')
  })

  it('separates the condition from the value for an expression mapping', async () => {
    const app = await openPdtCodeBranches()
    const drawer = await openDetails(app, cardsIn(app.choices)[1])
    const expression = await within(drawer).findByRole('region', { name: 'Expression' })
    expect(expression.querySelector('.expr-block.when')?.textContent).toContain('ELSE')
    expect(expression.querySelector('.expr-block.value')?.textContent).toContain('"OFFER"')
    expect(expression.querySelector('.expr-block.when')?.textContent).not.toContain('"OFFER"')
    expect(textOf(expression)).toContain('Condition · when')
    expect(textOf(expression)).toContain('Value · result')
  })

  it('lists the operands of an expression', async () => {
    const app = await openPdtCodeBranches()
    const drawer = await openDetails(app, cardsIn(app.choices)[0])
    const operands = await within(drawer).findByRole('region', { name: 'Operands' })
    expect(within(operands).getAllByRole('listitem').length).toBeGreaterThan(0)
  })

  it('shows exactly what the API holds for the same step', async () => {
    const client = realClient()
    const app = await openPdtCodeBranches()
    const card = cardsIn(app.choices)[0]
    const drawer = await openDetails(app, card)
    await within(drawer).findByRole('region', { name: 'Mapping' })

    const root = (await fetch(`${process.env.TEST_API_BASE}/targets?project=SP_CLO`).then((r) => r.json())).find(
      (o: { object_name: string }) => o.object_name === 'AR_PAR_LOAN_EVENTS',
    )
    const columns = await client.columns('SP_CLO', root.object_id)
    const target = { project: 'SP_CLO', objectId: root.object_id, columnId: columns.find((c) => c.column_name === 'PDT_CODE')!.column_id }
    const [rootChoice] = (await client.rootChoices(target)).choices
    const branch = (await client.upstream(rootChoice.step_id)).choices.find((c) => c.driving_expression?.includes('E011'))!
    const detail: StepDetail = await client.stepDetail(branch.step_id)

    const mapping = textOf(section(drawer, 'Mapping'))
    expect(mapping).toContain(`${detail.source.object_name}.${detail.source.column_name}`)
    expect(mapping).toContain(`${detail.target.object_name}.${detail.target.column_name}`)
    expect(mapping).toContain(detail.component.component_name!)
    expect(textOf(section(drawer, 'Confidence'))).toContain(detail.confidence.confidence_class!)
    expect(section(drawer, 'Expression').querySelector('.expr-block.when code')?.textContent).toBe(detail.driving_expression)
    expect(section(drawer, 'Expression').querySelector('.expr-block.value code')?.textContent).toBe(detail.result_expression)
    expect(within(section(drawer, 'Operands')).getAllByRole('listitem')).toHaveLength(detail.dependencies.length)
  })

  it('shows the stored reason for a not-persisted mapping', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'END_DATE')
    await app.user.click(cardWith(cardsIn(app.choices), '1 upstream choice'))
    await advance(app, 2)
    const drawer = await openDetails(app, cardsIn(app.choices)[0])
    const persistence = await within(drawer).findByRole('region', { name: 'Persistence' })
    expect(textOf(persistence)).toContain('NOT_PERSISTED')
    expect(textOf(persistence)).toContain('TARGET_ATTRIBUTE_ABSENT_FROM_EDF_MAPPING')
  })

  it('has no expression or persistence section for a plain mapping', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const drawer = await openDetails(app, cardsIn(app.choices)[0])
    await within(drawer).findByRole('region', { name: 'Mapping' })
    expect(within(drawer).queryByRole('region', { name: 'Expression' })).toBeNull()
    expect(within(drawer).queryByRole('region', { name: 'Persistence' })).toBeNull()
  })

  it('hides IDs until the developer toggle is on, and keeps the choice across cards', async () => {
    const app = await openPdtCodeBranches()
    const cards = cardsIn(app.choices)
    let drawer = await openDetails(app, cards[0])
    await within(drawer).findByRole('region', { name: 'Mapping' })
    expect(within(drawer).queryByRole('region', { name: 'Developer details' })).toBeNull()
    expect(textOf(drawer)).not.toMatch(/BLS_|MAP_|EXP_/)

    await app.user.click(within(drawer).getByLabelText('Show developer details'))
    const first = textOf(await within(drawer).findByRole('region', { name: 'Developer details' }))
    expect(first).toMatch(/BLS_/)
    expect(first).toMatch(/MAP_/)
    expect(first).toMatch(/EXP_/)

    // Another card, same toggle: the two CASE branches have different step and expression IDs.
    drawer = await openDetails(app, cards[1])
    const secondRegion = await within(drawer).findByRole('region', { name: 'Developer details' })
    await waitFor(() => expect(textOf(secondRegion)).not.toBe(first))
    expect((within(drawer).getByLabelText('Show developer details') as HTMLInputElement).checked).toBe(true)
  })

  it('shows one drawer at a time and replaces its content', async () => {
    const app = await openPdtCodeBranches()
    const cards = cardsIn(app.choices)
    let drawer = await openDetails(app, cards[0])
    await waitFor(() => expect(textOf(section(drawer, 'Expression'))).toContain('E011'))
    drawer = await openDetails(app, cards[1])
    await waitFor(() => expect(textOf(section(drawer, 'Expression'))).toContain('ELSE'))
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    expect(detailsButton(cards[0]).getAttribute('aria-expanded')).toBe('false')
    expect(detailsButton(cards[1]).getAttribute('aria-expanded')).toBe('true')
  })

  it('closes with the button and with Escape, returning focus to the card', async () => {
    const app = await openPdtCodeBranches()
    const trigger = detailsButton(cardsIn(app.choices)[0])
    let drawer = await openDetails(app, cardsIn(app.choices)[0])
    await app.user.click(within(drawer).getByRole('button', { name: 'Close details' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)

    drawer = await openDetails(app, cardsIn(app.choices)[0])
    await app.user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })

  it('does not change the walkthrough while it is open', async () => {
    const app = await openPdtCodeBranches()
    const cards = cardsIn(app.choices)
    await app.user.click(cards[1])
    // The remaining depth loads after the click; compare only once it has settled.
    await waitFor(() => expect(app.rail.querySelector('.rail-summary')?.textContent).not.toContain('Calculating'))
    const before = { hop: hopContext(app.choices), dots: app.rail.textContent, crumbs: app.crumbs.textContent, pressed: cards.map(pressed) }
    await openDetails(app, cards[0])
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    expect({ hop: hopContext(app.choices), dots: app.rail.textContent, crumbs: app.crumbs.textContent, pressed: cardsIn(app.choices).map(pressed) }).toEqual(before)
    expect(app.next().disabled).toBe(true)
  })

  it('closes when the user moves to another level', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const chain = cardWith(cardsIn(app.choices), '1 upstream choice')
    await app.user.click(chain)
    await openDetails(app, chain)
    expect(screen.getByRole('dialog')).toBeTruthy()
    await advance(app, 2)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('reports a failed load and recovers on Retry', async () => {
    let fail = true
    const flaky: typeof fetch = (input, init) =>
      fail && String(input).includes('/steps/') ? Promise.resolve(new Response(JSON.stringify({ error: { code: 'DATABASE_UNAVAILABLE', message: 'The lineage database is unavailable.' } }), { status: 503 })) : fetch(input, init)
    const app = await openApp(realClient({ fetchImpl: flaky }), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const drawer = await openDetails(app, cardsIn(app.choices)[0])
    const alert = await within(drawer).findByRole('alert')
    expect(alert.textContent).toContain('The lineage database is unavailable.')
    fail = false
    await app.user.click(within(alert).getByRole('button', { name: 'Retry' }))
    expect(await within(drawer).findByRole('region', { name: 'Mapping' })).toBeTruthy()
  })
})

describe('relation detail drawer with a scripted client', () => {
  it('shows loading while the detail is fetched', async () => {
    const { treeClient } = await import('./appHelpers')
    const { client } = treeClient()
    let release!: (d: StepDetail) => void
    const slow: ApiClient = { ...client, stepDetail: () => new Promise<StepDetail>((resolve) => { release = resolve }) }
    const app = await openApp(slow, 'ORDERS', 'ID')
    const drawer = await openDetails(app, cardsIn(app.choices)[0])
    expect((await within(drawer).findByRole('status')).textContent).toBe('Loading details…')
    release({
      step_id: 'p1', path_id: 'p1', lineage_level: 0, hop_count: 1, relation_id: 'r-p1', relation_type: 'EXPLICIT_INATTR',
      source: { object_id: 'o', object_name: 'SRC', object_type: 'DataObject', column_id: 'c', column_name: 'p1' },
      target: { object_id: 'o', object_name: 'TGT', object_type: 'DataObject', column_id: 'c', column_name: 'T' },
      component: { component_id: null, component_name: 'Comp', component_type: null },
      business_process: { business_process_id: null, business_process_name: 'BP' },
      confidence: { confidence_class: 'Explicit', reason_code: null, reason: null },
      traversal_path: null, expression_id: null, driving_expression: null, result_expression: null,
      dependencies: [], persistence: null, step_ids: ['p1'],
    })
    expect(await within(drawer).findByRole('region', { name: 'Mapping' })).toBeTruthy()
    expect(document.body.textContent).toContain('SRC.p1')
  })
})
