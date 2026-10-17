import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../ui/src/App'
import type { ApiClient } from '../../ui/src/api/client'
import type { Choice, TerminalSource } from '../../ui/src/api/types'

export const select = (name: string) => screen.getByLabelText(name) as HTMLSelectElement
export const optionTexts = (el: HTMLSelectElement) => Array.from(el.options).map((o) => o.textContent)

export const cardsIn = (scope: HTMLElement) => {
  const list = within(scope).queryByRole('list', { name: 'Upstream mappings' })
  return list ? within(list).queryAllByRole('listitem').map((li) => li.querySelector('button.card') as HTMLElement) : []
}
export const cardTitles = (scope: HTMLElement) => cardsIn(scope).map((c) => c.querySelector('.card-title')?.textContent)
export const pressed = (card: HTMLElement) => card.getAttribute('aria-pressed') === 'true'
export const sourceNames = (scope: HTMLElement) =>
  within(scope).queryAllByRole('listitem').map((li) => li.querySelector('.source-name')?.textContent)

export async function openApp(client: ApiClient, objectName: string, columnName: string) {
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
    rail: within(choices).getByRole('group', { name: 'Hop progress' }),
    crumbs: within(choices).getByRole('navigation', { name: 'Lineage path' }),
    next: () => within(choices).getByRole('button', { name: 'Next' }) as HTMLButtonElement,
    back: () => within(choices).getByRole('button', { name: 'Back' }) as HTMLButtonElement,
  }
}

/** "Hop 2 · upstream of X" assembled from the hop badge and the endpoint being explored. */
export const hopContext = (scope: HTMLElement) => {
  const hop = within(scope).queryByText(/^Hop \d+$/)?.textContent
  const endpoint = within(scope).queryByText(/^Upstream of/)?.querySelector('strong')?.textContent
  return hop && endpoint ? `${hop} · upstream of ${endpoint}` : null
}

/** The dots currently drawn in a rail, as glyphs. */
export const railGlyphs = (rail: HTMLElement) =>
  Array.from(rail.querySelectorAll('.rail-dots .dot')).map((d) => d.textContent)

// The approved example: p1 -> p1.1, p1.2; p2 -> p2.1; p3 -> p3.1. A scripted client lets us count calls.
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
const routeLengths = (id: string): number[] =>
  children[id] ? children[id].flatMap((c) => routeLengths(c).map((n) => n + 1)) : [0]
const terminal = (id: string): TerminalSource => ({
  terminal_id: id, object_id: 'o', column_id: `c-${id}`, object_name: 'SRC', column_name: id,
  object_type: 'DataObject', condition: null, result_expression: null, leaf_relation_types: ['EXPLICIT_INATTR'],
})

export function treeClient() {
  const upstreamCalls: string[] = []
  const depthCalls: string[] = []
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
    remainingDepth: async (stepId) => {
      depthCalls.push(stepId)
      const lengths = routeLengths(stepId)
      const min = Math.min(...lengths)
      const max = Math.max(...lengths)
      return {
        step_id: stepId, is_terminal: max === 0,
        remaining_hops_exact: min === max ? min : null, remaining_hops_min: min, remaining_hops_max: max,
      }
    },
    ultimateSources: async (t, _signal, stepId) => ({
      project: t.project, object_id: t.objectId, column_id: t.columnId, step_id: stepId ?? null,
      terminal_sources: (stepId ? leaves(stepId) : children.root.flatMap(leaves)).map(terminal),
    }),
  }
  return { client, upstreamCalls, depthCalls }
}

type App = Awaited<ReturnType<typeof openApp>>

/** Clicks Next and waits for the next level, because its choices are fetched. */
export async function advance(app: App, hop: number) {
  await app.user.click(app.next())
  await waitFor(() => expect(hopContext(app.choices)).toContain(`Hop ${hop} `))
  await waitFor(() => expect(cardsIn(app.choices).length).toBeGreaterThan(0))
}
