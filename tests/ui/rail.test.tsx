import { waitFor, within } from '@testing-library/react'
import type { ApiClient } from '../../src/ui/src/api/client'
import { advance, cardsIn, hopContext, openApp, pressed, railGlyphs, treeClient } from './appHelpers'
import { describeReal, realClient } from './helpers'

const FILLED = '●'
const CURRENT = '◉'
const HOLLOW = '○'
const MORE = '⋯'

const crumbs = (nav: HTMLElement) => Array.from(nav.querySelectorAll('li')).map((li) => li.textContent)
const summary = (rail: HTMLElement) => rail.querySelector('.rail-summary')?.textContent

describeReal('hop progress rail on the real SP_CLO lineage', () => {
  it('shows no dots and no depth request until a branch is selected', async () => {
    const calls: string[] = []
    const spy: typeof fetch = (input, init) => {
      calls.push(String(input))
      return fetch(input, init)
    }
    const { rail } = await openApp(realClient({ fetchImpl: spy }), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    expect(railGlyphs(rail)).toEqual([])
    expect(summary(rail)).toContain('Select a mapping')
    expect(calls.filter((c) => c.includes('remaining-depth'))).toHaveLength(0)
  })

  it('walks FDK_MT: filled dots grow, hollow dots shrink, selected hop is marked', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices, rail } = app

    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    await waitFor(() => expect(railGlyphs(rail)).toEqual([CURRENT, HOLLOW, HOLLOW, HOLLOW]))
    expect(summary(rail)).toBe('3 hops remaining.')

    await advance(app, 2)
    await waitFor(() => expect(railGlyphs(rail)).toEqual([FILLED, HOLLOW, HOLLOW, HOLLOW]))
    await user.click(cardsIn(choices)[0])
    await waitFor(() => expect(railGlyphs(rail)).toEqual([FILLED, CURRENT, HOLLOW, HOLLOW]))
    expect(summary(rail)).toBe('2 hops remaining.')

    await advance(app, 3)
    await user.click(cardsIn(choices)[0])
    await waitFor(() => expect(railGlyphs(rail)).toEqual([FILLED, FILLED, CURRENT, HOLLOW]))
    expect(summary(rail)).toBe('1 hop remaining.')

    await advance(app, 4)
    await waitFor(() => expect(cardsIn(choices)).toHaveLength(3))
    await user.click(cardsIn(choices)[0])
    await waitFor(() => expect(railGlyphs(rail)).toEqual([FILLED, FILLED, FILLED, CURRENT]))
    // The same glyphs appear while the depth is still loading, so wait for the text.
    await waitFor(() => expect(summary(rail)).toBe('End of this branch.'))
  })

  it('selecting a terminal choice shows only the selected hop', async () => {
    const { user, choices, rail } = await openApp(realClient(), 'PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)', 'CONTRACT_ID')
    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('nothing further upstream'))!)
    await waitFor(() => expect(railGlyphs(rail)).toEqual([CURRENT]))
    await waitFor(() => expect(summary(rail)).toBe('End of this branch.'))
  })

  it('never draws dots for sibling mappings that were not selected', async () => {
    const { user, choices, rail } = await openApp(
      realClient(),
      'PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)',
      'CONTRACT_ID',
    )
    expect(cardsIn(choices)).toHaveLength(3)
    await user.click(cardsIn(choices)[2])
    await waitFor(() => expect(railGlyphs(rail)[0]).toBe(CURRENT))
    expect(railGlyphs(rail).filter((g) => g === CURRENT || g === FILLED)).toHaveLength(1)
  })

  it('asks for remaining depth only for the active branch', async () => {
    const calls: string[] = []
    const spy: typeof fetch = (input, init) => {
      calls.push(String(input))
      return fetch(input, init)
    }
    const { user, choices, rail } = await openApp(
      realClient({ fetchImpl: spy }),
      'PAR_UNPROCESSED_EVENTS (SP_CLO · AR_CLO_EVENT_PROCESSING)',
      'CONTRACT_ID',
    )
    const cards = cardsIn(choices)
    await user.click(cards[0])
    await waitFor(() => expect(railGlyphs(rail)).toEqual([CURRENT]))
    await user.click(cards[2])
    await waitFor(() => expect(railGlyphs(rail).length).toBeGreaterThan(1))
    const depthCalls = calls.filter((c) => c.includes('remaining-depth'))
    expect(depthCalls).toHaveLength(2)
    expect(new Set(depthCalls).size).toBe(2)
  })

  it('clicking a completed dot returns to that hop with its mapping selected', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices, rail, crumbs: nav } = app
    const chain = cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!
    await user.click(chain)
    await advance(app, 2)
    await user.click(cardsIn(choices)[0])
    await advance(app, 3)
    await waitFor(() => expect(railGlyphs(rail).filter((g) => g === FILLED)).toHaveLength(2))

    await user.click(within(rail).getByRole('button', { name: /^Hop 1:/ }))
    await waitFor(() => expect(hopContext(choices)).toContain('Hop 1 · upstream of CM_PAR_LOAN_TRADES.FDK_MT'))
    const restored = cardsIn(choices)
    expect(restored).toHaveLength(2)
    expect(pressed(restored.find((c) => c.textContent?.includes('1 upstream choice'))!)).toBe(true)
    await waitFor(() => expect(railGlyphs(rail)).toEqual([CURRENT, HOLLOW, HOLLOW, HOLLOW]))
    expect(crumbs(nav)).toEqual(['CM_PAR_LOAN_TRADES.FDK_MT', 'CM_CLO_OFFER.e_fdk_mt'])
  })

  it('jumps to the middle hop and keeps the earlier hops', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices, rail } = app
    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    await advance(app, 2)
    await user.click(cardsIn(choices)[0])
    await advance(app, 3)
    await user.click(cardsIn(choices)[0])
    await advance(app, 4)
    await waitFor(() => expect(railGlyphs(rail).filter((g) => g === FILLED)).toHaveLength(3))

    await user.click(within(rail).getByRole('button', { name: /^Hop 2:/ }))
    await waitFor(() => expect(hopContext(choices)).toContain('Hop 2'))
    expect(railGlyphs(rail).filter((g) => g === FILLED)).toHaveLength(1)
    expect(cardsIn(choices)).toHaveLength(1)
    expect(pressed(cardsIn(choices)[0])).toBe(true)
  })

  it('gives each completed dot an accessible name, tooltip and keyboard access', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices, rail } = app
    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    await advance(app, 2)
    const dot = await within(rail).findByRole('button', { name: /^Hop 1:/ })
    expect(dot.getAttribute('aria-label')).toBe('Hop 1: CM_CLO_OFFER.e_fdk_mt, Direct mapping. Go back to this hop.')
    expect(dot.getAttribute('title')).toBe('Hop 1: CM_CLO_OFFER.e_fdk_mt (Direct mapping)')
    await user.tab({ shift: false })
    dot.focus()
    expect(document.activeElement).toBe(dot)
    await user.keyboard('{Enter}')
    await waitFor(() => expect(hopContext(choices)).toContain('Hop 1'))
  })

  it('keeps a textual breadcrumb that follows the walk', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices, crumbs: nav } = app
    expect(crumbs(nav)).toEqual(['CM_PAR_LOAN_TRADES.FDK_MT'])
    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    expect(crumbs(nav)).toEqual(['CM_PAR_LOAN_TRADES.FDK_MT', 'CM_CLO_OFFER.e_fdk_mt'])
    await advance(app, 2)
    await user.click(cardsIn(choices)[0])
    await waitFor(() =>
      expect(crumbs(nav)).toEqual([
        'CM_PAR_LOAN_TRADES.FDK_MT',
        'CM_CLO_OFFER.e_fdk_mt',
        'FSD_FO_DESKS.FDK_MT',
      ]),
    )
    expect(nav.querySelector('[aria-current="step"]')?.textContent).toBe('FSD_FO_DESKS.FDK_MT')
  })
})

describe('hop progress rail on the p1/p2/p3 example', () => {
  const open = (client: ApiClient) => openApp(client, 'ORDERS', 'ID')

  it('selecting p1 and advancing creates one completed dot, not three', async () => {
    const { client } = treeClient()
    const { user, choices, rail, next } = await open(client)
    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await waitFor(() => expect(railGlyphs(rail).filter((g) => g === FILLED)).toHaveLength(1))
    expect(railGlyphs(rail).filter((g) => g === CURRENT)).toHaveLength(0)
  })

  it('a second advance adds the second completed dot; clicking the first returns to the p1 state', async () => {
    const { client } = treeClient()
    const { user, choices, rail, next } = await open(client)
    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await user.click(cardsIn(choices)[1])
    await user.click(next())
    await waitFor(() => expect(railGlyphs(rail).filter((g) => g === FILLED)).toHaveLength(2))

    await user.click(within(rail).getByRole('button', { name: /^Hop 1:/ }))
    await waitFor(() => expect(railGlyphs(rail).filter((g) => g === FILLED)).toHaveLength(0))
    const roots = cardsIn(choices)
    expect(roots.map((c) => c.querySelector('.card-title')?.textContent)).toEqual(['SRC.p1', 'SRC.p2', 'SRC.p3'])
    expect(roots.map(pressed)).toEqual([true, false, false])
  })

  it('shows a range and an ellipsis when routes below the selection differ in length', async () => {
    const { client } = treeClient()
    const { user, choices, rail } = await open(client)
    await user.click(cardsIn(choices)[0]) // p1: routes of 1 and 2 hops below it
    await waitFor(() => expect(railGlyphs(rail)).toEqual([CURRENT, HOLLOW, MORE]))
    expect(summary(rail)).toBe('1–2 hops remaining.')
  })

  it('shows an exact count when all routes below the selection have the same length', async () => {
    const { client } = treeClient()
    const { user, choices, rail } = await open(client)
    await user.click(cardsIn(choices)[1]) // p2 -> p2.1 -> three leaves
    await waitFor(() => expect(railGlyphs(rail)).toEqual([CURRENT, HOLLOW, HOLLOW]))
    expect(summary(rail)).toBe('2 hops remaining.')
  })

  it('measures depth only for the branch the user is on', async () => {
    const { client, depthCalls } = treeClient()
    const { user, choices, next } = await open(client)
    expect(depthCalls).toEqual([])
    await user.click(cardsIn(choices)[0])
    await user.click(next())
    await waitFor(() => expect(depthCalls).toContain('p1'))
    expect(depthCalls.every((id) => id === 'p1' || id.startsWith('p1.'))).toBe(true)
  })

  it('reports when remaining hops cannot be loaded', async () => {
    const { client } = treeClient()
    const failing: ApiClient = { ...client, remainingDepth: async () => { throw new Error('boom') } }
    const { user, choices, rail } = await open(failing)
    await user.click(cardsIn(choices)[0])
    await waitFor(() => expect(summary(rail)).toBe('Remaining hops are unavailable.'))
    expect(railGlyphs(rail)).toEqual([CURRENT])
  })
})
