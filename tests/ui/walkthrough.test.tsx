import { screen, waitFor, within } from '@testing-library/react'
import { select, optionTexts, cardsIn, cardTitles, pressed, sourceNames, openApp, treeClient, hopContext, advance } from './appHelpers'
import { describeReal, realClient } from './helpers'

describeReal('hop-by-hop walkthrough on the real SP_CLO lineage', () => {
  it('walks the four-hop FDK_MT chain forward and back without ever showing sibling routes', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices, target, sources } = app
    const targetBefore = target.textContent

    // Hop 1: two mappings reach the same endpoint, and both continue the same way.
    expect(app.back().disabled).toBe(true)
    expect(app.next().disabled).toBe(true)
    expect(hopContext(choices)).toContain('Step 1 · upstream of CM_PAR_LOAN_TRADES.FDK_MT')
    const root = cardsIn(choices)
    expect(root).toHaveLength(2)
    const chain = root.find((c) => c.textContent?.includes('1 upstream choice'))!
    await user.click(chain)
    expect(app.next().disabled).toBe(false)
    await user.click(app.next())

    // Hop 2: the sibling root route is gone.
    await waitFor(() => expect(hopContext(choices)).toContain('Step 2 · upstream of CM_CLO_OFFER.e_fdk_mt'))
    await waitFor(() => expect(cardTitles(choices)).toEqual(['FSD_FO_DESKS.FDK_MT']))
    expect(app.back().disabled).toBe(false)
    expect(app.next().disabled).toBe(true)
    await waitFor(() => expect(sourceNames(sources)).toHaveLength(3))
    expect(target.textContent).toBe(targetBefore)

    await user.click(cardsIn(choices)[0])
    await user.click(app.next())

    // Hop 3: the enrichment lookup.
    await waitFor(() => expect(hopContext(choices)).toContain('Step 3 · upstream of FSD_FO_DESKS.FDK_MT'))
    await waitFor(() => expect(cardTitles(choices)).toEqual(['CM_CLO_OFFER.e_bok_code']))
    expect(cardsIn(choices)[0].textContent).toContain('Lookup')
    await user.click(cardsIn(choices)[0])
    await user.click(app.next())

    // Hop 4: three sibling terminal columns.
    await waitFor(() => expect(hopContext(choices)).toContain('Ultimate sources · upstream of CM_CLO_OFFER.e_bok_code'))
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
    await waitFor(() => expect(hopContext(choices)).toContain('Step 3'))
    expect(cardTitles(choices)).toEqual(['CM_CLO_OFFER.e_bok_code'])
    expect(pressed(cardsIn(choices)[0])).toBe(true)
    await user.click(app.back())
    expect(cardTitles(choices)).toEqual(['FSD_FO_DESKS.FDK_MT'])
    expect(pressed(cardsIn(choices)[0])).toBe(true)
    await user.click(app.back())

    expect(hopContext(choices)).toContain('Step 1')
    const restored = cardsIn(choices)
    expect(restored).toHaveLength(2)
    expect(restored.map(pressed)).toEqual([true, false])
    await waitFor(() => expect(sourceNames(sources)).toHaveLength(3))
    expect(app.back().disabled).toBe(true)
    expect(target.textContent).toBe(targetBefore)
  })

  it('gives both mappings that reach one endpoint the same upstream (CONTRACT_ID)', async () => {
    const seen: string[][] = []
    for (const index of [0, 1]) {
      const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'CONTRACT_ID')
      const cards = cardsIn(app.choices)
      expect(cards).toHaveLength(2)
      expect(cards.map((c) => c.textContent?.includes('3 upstream choices'))).toEqual([true, true])
      expect(new Set(cards.map((c) => c.textContent?.match(/CM_CLO_OFR_[\w ]+Mapping/)?.[0])).size).toBe(2)
      await app.user.click(cards[index])
      await advance(app, 2)
      await waitFor(() => expect(cardsIn(app.choices)).toHaveLength(3))
      seen.push(cardsIn(app.choices).map((c) => c.textContent ?? '').sort())
      document.body.innerHTML = ''
    }
    expect(seen[0]).toEqual(seen[1])
    expect(seen[0].every((t) => t.includes('CM_CLO_OFFER.OFR_ID'))).toBe(true)
  })

  it('does not allow Next on a terminal choice', async () => {
    const { user, choices, next } = await openApp(realClient(), 'PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)', 'CONTRACT_ID')
    const leaf = cardsIn(choices).find((c) => c.textContent?.includes('nothing further upstream'))!
    await user.click(leaf)
    expect(pressed(leaf)).toBe(true)
    expect(next().disabled).toBe(true)
    expect(next().title).toBe('Nothing further upstream')
    expect(cardsIn(choices)).toHaveLength(3)
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
    await waitFor(() => expect(hopContext(choices)).toContain('Step 2 · upstream of AR_CLO_ACCOUNTING_EVENTS.e_contract_id'))
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
    await waitFor(() => expect(hopContext(choices)).toContain('Step 2'))

    await user.selectOptions(select('Target Object'), 'AR_PAR_LOAN_EVENTS')
    await waitFor(() => expect(optionTexts(select('Target Column')).length).toBeGreaterThan(1))
    await user.selectOptions(select('Target Column'), 'MDE_CODE')
    const workspace = await screen.findByRole('region', { name: 'Lineage session' })
    const fresh = within(workspace).getByRole('region', { name: 'Upstream choices' })
    await waitFor(() => expect(hopContext(fresh)).toContain('Step 1 · upstream of AR_PAR_LOAN_EVENTS.MDE_CODE'))
    expect(within(fresh).getByRole('button', { name: /^Back/ }).hasAttribute('disabled')).toBe(true)
    expect(cardsIn(fresh).every((c) => !pressed(c))).toBe(true)
  })
})

describe('single-branch navigation on the p1/p2/p3 example', () => {
  const scripted = treeClient

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
