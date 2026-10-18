import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../src/ui/src/App'
import { createApiClient, type ApiClient } from '../../src/ui/src/api/client'
import { cardsIn, openApp } from './appHelpers'
import { describeReal, realClient } from './helpers'

function show(client: ApiClient, hash: string) {
  cleanup()
  window.history.replaceState(null, '', hash)
  const user = userEvent.setup()
  render(<App client={client} />)
  return user
}

const scripted = (projects: { project_name: string; ready?: boolean; problem?: string }[]): ApiClient => ({
  projects: async () => projects,
  targets: async () => [],
  columns: async () => [],
  searchTargets: async () => [],
  tableSummary: async () => { throw new Error('unused') },
  rootChoices: async () => ({ choices: [] }),
  upstream: async () => ({ choices: [] }),
  remainingDepth: async () => { throw new Error('unused') },
  stepDetail: async () => { throw new Error('unused') },
  ultimateSources: async (t) => ({ project: t.project, object_id: t.objectId, column_id: t.columnId, step_id: null, terminal_sources: [] }),
})

const projects = [
  { project_name: 'GP_BROKEN', ready: false, problem: 'The database needs to be migrated (run ./start.sh --migrate).' },
  { project_name: 'SP_CLO' },
  { project_name: 'SP_LIQ' },
]

describe('choosing a project on the summary page', () => {
  it('lists every project database, and explains the ones that cannot be used yet', async () => {
    show(scripted(projects), '#/summary')
    const select = (await screen.findByLabelText('Project')) as HTMLSelectElement
    const options = Array.from(select.options).map((o) => ({ text: o.textContent, disabled: o.disabled }))
    expect(options).toEqual([
      { text: 'Select a project', disabled: false },
      { text: 'GP_BROKEN (not ready)', disabled: true },
      { text: 'SP_CLO', disabled: false },
      { text: 'SP_LIQ', disabled: false },
    ])
    expect(document.body.textContent).toContain('GP_BROKEN: The database needs to be migrated')
    expect(screen.getByText('Choose a project to see its target tables.')).toBeTruthy()
    expect(screen.queryByLabelText('Search target tables')).toBeNull()
  })

  it('opens the chosen project and keeps the choice in the address', async () => {
    const user = show(scripted(projects), '#/summary')
    await user.selectOptions(await screen.findByLabelText('Project'), 'SP_LIQ')
    expect(await screen.findByLabelText('Search target tables')).toBeTruthy()
    expect(window.location.hash).toBe('#/summary/SP_LIQ')
  })

  it('does not pick a single project by itself when it cannot be used', async () => {
    show(scripted([projects[0]]), '#/summary')
    expect((await screen.findByText(/^GP_BROKEN: The database needs to be migrated/)).textContent).toContain('--migrate')
    expect(screen.queryByLabelText('Search target tables')).toBeNull()
  })

  it('offers the same projects, with the unusable one disabled, in the walkthrough', async () => {
    show(scripted(projects), '#/lineage')
    const select = (await screen.findByLabelText('Project')) as HTMLSelectElement
    await within(select).findByRole('option', { name: 'SP_CLO' })
    const broken = within(select).getByRole('option', { name: 'GP_BROKEN (not ready)' }) as HTMLOptionElement
    expect(broken.disabled).toBe(true)
  })
})

describe('requests for one project', () => {
  const capture = () => {
    const seen: { url: string; project: string | null }[] = []
    const fetchImpl: typeof fetch = async (input, init) => {
      const headers = new Headers(init?.headers)
      seen.push({ url: String(input), project: headers.get('X-Lineage-Project') })
      return new Response('[]', { status: 200 })
    }
    return { seen, fetchImpl }
  }

  it('sends no project header until a client is bound to a project', async () => {
    const { seen, fetchImpl } = capture()
    const client = createApiClient({ sessionId: 's', fetchImpl })
    await client.projects()
    await client.forProject!('SP_LIQ').projects()
    expect(seen.map((s) => s.project)).toEqual([null, 'SP_LIQ'])
  })
})

describeReal('walkthrough requests that carry no project of their own', () => {
  it('name the project in a header', async () => {
    const seen: { url: string; project: string | null }[] = []
    const spy: typeof fetch = (input, init) => {
      seen.push({ url: String(input), project: new Headers(init?.headers).get('X-Lineage-Project') })
      return fetch(input, init)
    }
    const app = await openApp(realClient({ fetchImpl: spy }), 'CM_PAR_LOAN_TRADES', 'FDK_MT')
    await app.user.click(cardsIn(app.choices).find((c) => c.textContent?.includes('1 upstream choice'))!)
    await app.user.click(app.next())
    await app.user.click((await within(app.choices).findAllByRole('button', { name: /^Details for/ }))[0])
    await waitFor(() => expect(seen.some((s) => s.url.includes('/steps/'))).toBe(true))
    await waitFor(() => expect(seen.some((s) => s.url.includes('/lineage/upstream?step_id'))).toBe(true))

    const stepLevel = seen.filter((s) => /\/lineage\/(upstream\?step_id|remaining-depth)|\/steps\//.test(s.url))
    expect(stepLevel.length).toBeGreaterThan(2)
    expect(stepLevel.every((s) => s.project === 'SP_CLO')).toBe(true)
  })
})
