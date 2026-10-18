import { waitFor, within } from '@testing-library/react'
import { cardsIn, openApp } from './appHelpers'
import { describeReal, realClient } from './helpers'

const text = (el: Element | null) => el?.textContent ?? ''
const instruction = (scope: HTMLElement) => text(scope.querySelector('.walk-instruction'))

describeReal('walkthrough guidance on the real SP_CLO lineage', () => {
  it('pins one Back/Next strip above the choices, with the hop dots between the buttons', async () => {
    const { choices, rail } = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const bar = choices.querySelector('.walk-bar')!
    const controls = bar.querySelector('.walk-controls')!
    expect(Array.from(controls.children).map((c) => c.tagName + (c.className.includes('rail') ? '.rail' : ''))).toEqual([
      'BUTTON',
      'DIV.rail',
      'BUTTON',
    ])
    expect(controls.contains(rail)).toBe(true)
    // The strip comes before the list of mappings, so it is on screen before the user scrolls.
    const list = within(choices).getByRole('list', { name: 'Upstream mappings' })
    expect(bar.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(within(choices).getAllByRole('button', { name: /^Back/ })).toHaveLength(1)
    expect(within(choices).getAllByRole('button', { name: /^Next/ })).toHaveLength(1)
    expect(within(choices).getByRole('heading', { name: 'Where does this come from?' })).toBeTruthy()
    expect(within(choices).getByRole('heading', { name: 'Pick one to follow' })).toBeTruthy()
  })

  it('says what to do, and names where Back and Next lead', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices } = app

    expect(instruction(choices)).toBe('Pick the mapping you want to follow, then press Next.')
    expect(text(app.back())).toContain('Start of path')
    expect(text(app.next())).toContain('Pick a mapping first')

    const chain = cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!
    await user.click(chain)
    expect(instruction(choices)).toBe('Press Next to see where CM_CLO_OFFER.e_fdk_mt comes from.')
    expect(text(app.next())).toContain('Go into CM_CLO_OFFER.e_fdk_mt')
    await waitFor(() => expect(text(choices.querySelector('.hop-badge'))).toBe('Step 1 of 3'))

    await user.click(app.next())
    await waitFor(() => expect(text(app.back())).toContain('to CM_PAR_LOAN_TRADES.FDK_MT'))
    await waitFor(() => expect(text(choices.querySelector('.hop-badge'))).toBe('Step 2'))
  })

  it('explains that an ultimate source ends the branch', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices } = app
    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    await user.click(app.next())
    await waitFor(() => expect(cardsIn(choices)).toHaveLength(1))
    await user.click(cardsIn(choices)[0])
    await user.click(app.next())
    await waitFor(() => expect(cardsIn(choices).length).toBeGreaterThan(0))
    await user.click(cardsIn(choices)[0])
    await user.click(app.next())
    await waitFor(() => expect(cardsIn(choices)).toHaveLength(3))
    expect(instruction(choices)).toBe('You have reached an ultimate source. Press Back to try another branch.')
    expect(text(choices.querySelector('.hop-badge'))).toBe('Ultimate sources')
    expect(text(app.next())).toContain('Pick a mapping first')
    await user.click(cardsIn(choices)[0])
    expect(instruction(choices)).toBe('You have reached an ultimate source. Press Back to try another branch.')
    expect(text(app.next())).toContain('Nothing further upstream')
    expect(app.next().disabled).toBe(true)
  })

  it('moves with the arrow keys', async () => {
    const app = await openApp(realClient(), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    const { user, choices } = app
    await user.click(cardsIn(choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    await user.keyboard('{ArrowRight}')
    await waitFor(() => expect(text(choices.querySelector('.hop-badge'))).toBe('Step 2'))
    await user.keyboard('{ArrowLeft}')
    await waitFor(() => expect(text(choices.querySelector('.hop-badge'))).toMatch(/^Step 1/))
    await user.keyboard('{ArrowLeft}')
    expect(text(choices.querySelector('.hop-badge'))).toMatch(/^Step 1/)
  })
})
