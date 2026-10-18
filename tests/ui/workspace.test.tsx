import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import { relationStyle } from '../../src/ui/src/components/relationStyle'
import { describeReal, realClient } from './helpers'

const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement
const optionTexts = (el: HTMLSelectElement) => Array.from(el.options).map((o) => o.textContent)

async function open(objectName: string, columnName: string) {
  cleanup()
  window.history.replaceState(null, '', '#/lineage')
  const user = userEvent.setup()
  render(<App client={realClient()} />)
  await waitFor(() => expect(optionTexts(select('Target Object')).length).toBeGreaterThan(1))
  await user.selectOptions(select('Target Object'), objectName)
  await waitFor(() => expect(optionTexts(select('Target Column')).length).toBeGreaterThan(1))
  await user.selectOptions(select('Target Column'), columnName)
  const workspace = await screen.findByRole('region', { name: 'Lineage session' })
  return {
    user,
    workspace,
    target: within(workspace).getByRole('region', { name: 'Target' }),
    choices: within(workspace).getByRole('region', { name: 'Upstream choices' }),
    sources: within(workspace).getByRole('region', { name: 'Ultimate sources' }),
  }
}

const mappings = (scope: HTMLElement) => within(scope).getByRole('list', { name: 'Upstream mappings' })
const getCards = (scope: HTMLElement) =>
  within(mappings(scope)).getAllByRole('listitem').map((li) => li.querySelector('button.card') as HTMLElement)
const findCards = async (scope: HTMLElement) => {
  await within(scope).findByRole('list', { name: 'Upstream mappings' })
  return getCards(scope)
}

const sourceNames = (sources: HTMLElement) =>
  within(sources).getAllByRole('listitem').map((li) => li.querySelector('.source-name')?.textContent)

describeReal('three-panel layout on the real SP_CLO lineage', () => {
  it('renders target, choices and sources as three panels in that order', async () => {
    const { workspace } = await open('AR_PAR_LOAN_EVENTS', 'MDE_CODE')
    const panels = within(workspace).getAllByRole('region').map((r) => r.getAttribute('aria-label'))
    expect(panels).toEqual(['Target', 'Upstream choices', 'Ultimate sources'])
  })

  it('shows the fixed target with its project and business process', async () => {
    const { target } = await open('AR_PAR_LOAN_EVENTS', 'MDE_CODE')
    expect(within(target).getByText('AR_PAR_LOAN_EVENTS')).toBeTruthy()
    expect(within(target).getByText('MDE_CODE')).toBeTruthy()
    expect(within(target).getByText('Project').nextElementSibling?.textContent).toBe('SP_CLO')
    expect(within(target).getByText('Source project').nextElementSibling?.textContent).toBe('SP_CLO')
    expect(within(target).getByText('AR_CLO_EVENT_PROCESSING')).toBeTruthy()
  })

  it('renders a choice card with endpoint, relation, confidence, component and upstream count', async () => {
    const { choices } = await open('AR_PAR_LOAN_EVENTS', 'MDE_CODE')
    const card = await within(choices).findByRole('button', { name: /^AR_CLO_ACCOUNTING_EVENTS\.e_product_group/ })
    expect(card.textContent).toContain('AR_CLO_ACCOUNTING_EVENTS.e_product_group')
    expect(card.textContent).toContain('Direct mapping (path)')
    expect(card.textContent).toContain('Explicit')
    expect(card.textContent).toContain('CLO_AR_LOAN Mapping')
    expect(card.textContent).toContain('2 upstream choices')
    expect(card.getAttribute('aria-pressed')).toBe('false')
  })

  it('shows terminal choices and an inferred relation distinctly', async () => {
    const { choices } = await open('PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)', 'CONTRACT_ID')
    const cards = await findCards(choices)
    expect(cards).toHaveLength(3)
    const text = cards.map((c) => c.textContent ?? '')
    expect(text.filter((t) => t.includes('Ultimate source · nothing further upstream'))).toHaveLength(2)
    expect(text.filter((t) => t.includes('1 upstream choice'))).toHaveLength(1)
  })

  it('lists every ultimate source of a multi-source target, with relation kinds', async () => {
    const { sources } = await open('CM_PAR_LOAN_TRADES', 'FDK_MT')
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(3))
    expect(sourceNames(sources)).toEqual([
      'CM_CLO_OFFER.OFR_HTCS_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTC_BOOK_CODE',
      'CM_CLO_OFFER.OFR_HTS_BOOK_CODE',
    ])
  })

  it('shows each CASE branch to a constant as its own source with its condition', async () => {
    const { sources } = await open('AR_PAR_LOAN_EVENTS', 'PDT_CODE')
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(2))
    const [first, second] = within(sources).getAllByRole('listitem')
    for (const item of [first, second]) {
      expect(item.querySelector('.source-name')?.textContent).toBe('"OFFER"."OFFER"')
      expect(item.textContent).toContain('Expression')
      expect(item.textContent).toContain('CONSTANT')
    }
    expect(first.querySelector('.source-condition')?.textContent).toBe('when AEF_EVENT_CODE=="E011"')
    expect(second.querySelector('.source-condition')?.textContent).toBe('when ELSE')
  })

  it('shows a constant ultimate source as a constant', async () => {
    const { sources } = await open('AR_PAR_LOAN_EVENTS', 'MDE_CODE')
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(2))
    expect(sources.textContent).toContain('Expression')
    expect(sources.textContent).toContain('CONSTANT')
  })

  it('does not add a condition line to sources without an expression', async () => {
    const { sources } = await open('CM_PAR_LOAN_TRADES', 'FDK_MT')
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(3))
    expect(sources.querySelector('.source-condition')).toBeNull()
  })

  it('selecting a branch filters the sources but keeps the choices and the target', async () => {
    const { user, target, choices, sources } = await open('PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)', 'CONTRACT_ID')
    await waitFor(() => expect(sourceNames(sources)).toEqual([
      'AR_CLO_ACCOUNTING_EVENTS.AEF_EVENT_CODE',
      'AR_CLO_ACCOUNTING_EVENTS.AEF_OFFER_ID',
    ]))
    const targetBefore = target.textContent
    const cards = await findCards(choices)
    expect(cards).toHaveLength(3)
    const [eventCode, offerId, contractId] = cards

    await user.click(eventCode)
    expect(eventCode.getAttribute('aria-pressed')).toBe('true')
    await waitFor(() => expect(sourceNames(sources)).toEqual(['AR_CLO_ACCOUNTING_EVENTS.AEF_EVENT_CODE']))

    await user.click(contractId)
    expect(contractId.getAttribute('aria-pressed')).toBe('true')
    expect(eventCode.getAttribute('aria-pressed')).toBe('false')
    await waitFor(() => expect(sourceNames(sources)).toEqual(['AR_CLO_ACCOUNTING_EVENTS.AEF_OFFER_ID']))
    expect(offerId.getAttribute('aria-pressed')).toBe('false')

    // The user stays at this level: the same three cards remain, the target is unchanged.
    expect(getCards(choices)).toHaveLength(3)
    expect(target.textContent).toBe(targetBefore)
  })

  it('clicking the selected card again clears the selection and restores all sources', async () => {
    const { user, choices, sources } = await open('PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)', 'CONTRACT_ID')
    const cards = await findCards(choices)
    await user.click(cards[0])
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(1))
    await user.click(cards[0])
    expect(cards[0].getAttribute('aria-pressed')).toBe('false')
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(2))
  })

  it('explains a direct mapping that has no intermediate steps', async () => {
    const { choices, sources } = await open('PAR_GFRS_CLO_TRADES', 'OFR_ACCEPTANCE_DATE')
    const cards = await findCards(choices)
    expect(cards).toHaveLength(1)
    expect(cards[0].textContent).toContain('Ultimate source')
    expect(cards[0].textContent).toContain('nothing further upstream')
    expect(choices.textContent).toContain('This mapping leads directly to the ultimate source; there are no intermediate steps.')
    await waitFor(() => expect(within(sources).getAllByRole('listitem')).toHaveLength(1))
  })

  it('shows no direct-mapping note when a choice continues upstream', async () => {
    const { choices } = await open('CM_PAR_LOAN_TRADES', 'FDK_MT')
    await findCards(choices)
    expect(choices.textContent).not.toContain('no intermediate steps')
    const mde = await open('AR_PAR_LOAN_EVENTS', 'MDE_CODE')
    await findCards(mde.choices)
    expect(mde.choices.textContent).not.toContain('no intermediate steps')
  })

  it('does not move into a branch on its own', async () => {
    const { choices } = await open('CM_PAR_LOAN_TRADES', 'FDK_MT')
    const cards = await findCards(choices)
    expect(cards.every((c) => c.getAttribute('aria-pressed') === 'false')).toBe(true)
  })

  it('discards the branch selection when another target is chosen', async () => {
    const { user, choices } = await open('CM_PAR_LOAN_TRADES', 'FDK_MT')
    const cards = await findCards(choices)
    await user.click(cards[0])
    await user.selectOptions(select('Target Object'), 'AR_PAR_LOAN_EVENTS')
    await waitFor(() => expect(optionTexts(select('Target Column')).length).toBeGreaterThan(1))
    await user.selectOptions(select('Target Column'), 'MDE_CODE')
    const workspace = await screen.findByRole('region', { name: 'Lineage session' })
    const next = await findCards(within(workspace).getByRole('region', { name: 'Upstream choices' }))
    expect(next.every((c) => c.getAttribute('aria-pressed') === 'false')).toBe(true)
  })
})

describe('relation styling tokens', () => {
  it('gives every relation type in the data a distinct readable label', () => {
    const types = [
      'EXPLICIT_INATTR', 'EXPLICIT_PATHFROM_PATHTO', 'AUTO_MAP_BY_NAME', 'EXPRESSION', 'CONSTANT_ASSIGNMENT',
      'ENRICHMENT_LOOKUP', 'RUNTIME_FUNCTION_ASSIGNMENT', 'TRANSFORMATION_AUTO_MAP_BY_NAME', 'NOT_PERSISTED',
    ]
    const labels = types.map((t) => relationStyle(t).label)
    expect(new Set(labels).size).toBe(types.length)
    expect(relationStyle('NOT_PERSISTED').tone).toBe('not-persisted')
    expect(relationStyle('CONSTANT_ASSIGNMENT').tone).toBe('constant')
  })

  it('falls back to a readable label for unknown relation types', () => {
    expect(relationStyle('SOMETHING_NEW')).toEqual({ label: 'Something new', tone: 'neutral' })
  })
})
