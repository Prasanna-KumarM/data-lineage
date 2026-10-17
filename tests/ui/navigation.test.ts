import type { Choice } from '../../ui/src/api/types'
import {
  activeStepId,
  initialNavigation,
  navigationReducer,
  type NavigationState,
} from '../../ui/src/state/navigation'

const choice = (id: string): Choice => ({
  step_id: id, relation_id: `r-${id}`, relation_type: 'EXPLICIT_INATTR',
  source_object_id: 'o', source_column_id: `c-${id}`, source_object_name: 'OBJ', source_column_name: id,
  target_object_id: 'o', target_column_id: 'c', target_object_name: 'OBJ', target_column_name: 'T',
  component_id: null, component_name: null, component_type: null,
  business_process_id: null, business_process_name: null,
  confidence_class: 'Explicit', confidence_reason_code: null,
  traversal_path: null, driving_expression: null, result_expression: null, expression_id: null,
  lineage_level: 0, is_terminal: false, has_more_upstream: true, upstream_choice_count: 1,
})

const run = (actions: Parameters<typeof navigationReducer>[1][], from: NavigationState = initialNavigation) =>
  actions.reduce(navigationReducer, from)

describe('navigationReducer', () => {
  it('starts at the root with nothing selected', () => {
    expect(initialNavigation).toEqual({ path: [], selectedStepId: null })
  })

  it('select highlights a choice without moving', () => {
    expect(run([{ type: 'select', stepId: 'p1' }])).toEqual({ path: [], selectedStepId: 'p1' })
  })

  it('selecting the same or another choice only changes the highlight', () => {
    const s = run([{ type: 'select', stepId: 'p1' }])
    expect(navigationReducer(s, { type: 'select', stepId: 'p1' })).toBe(s)
    expect(navigationReducer(s, { type: 'select', stepId: 'p2' }).selectedStepId).toBe('p2')
    expect(navigationReducer(s, { type: 'select', stepId: null }).selectedStepId).toBeNull()
  })

  it('next records the hop and clears the highlight', () => {
    const s = run([{ type: 'select', stepId: 'p1' }, { type: 'next', choice: choice('p1') }])
    expect(s.path.map((c) => c.step_id)).toEqual(['p1'])
    expect(s.selectedStepId).toBeNull()
  })

  it('back restores the selection that led out of the level', () => {
    const s = run([
      { type: 'next', choice: choice('p1') },
      { type: 'next', choice: choice('p1.2') },
      { type: 'back' },
    ])
    expect(s.path.map((c) => c.step_id)).toEqual(['p1'])
    expect(s.selectedStepId).toBe('p1.2')
    const root = navigationReducer(s, { type: 'back' })
    expect(root.path).toEqual([])
    expect(root.selectedStepId).toBe('p1')
  })

  it('back at the root changes nothing', () => {
    expect(navigationReducer(initialNavigation, { type: 'back' })).toBe(initialNavigation)
  })

  it('jump returns to an earlier hop with that hop selected', () => {
    const deep = run([
      { type: 'next', choice: choice('a') },
      { type: 'next', choice: choice('b') },
      { type: 'next', choice: choice('c') },
    ])
    const s = navigationReducer(deep, { type: 'jump', depth: 1 })
    expect(s.path.map((c) => c.step_id)).toEqual(['a'])
    expect(s.selectedStepId).toBe('b')
    expect(navigationReducer(deep, { type: 'jump', depth: 0 })).toMatchObject({ path: [], selectedStepId: 'a' })
  })

  it('jump outside the taken path changes nothing', () => {
    const s = run([{ type: 'next', choice: choice('a') }])
    expect(navigationReducer(s, { type: 'jump', depth: 1 })).toBe(s)
    expect(navigationReducer(s, { type: 'jump', depth: -1 })).toBe(s)
  })

  it('reports the branch being followed', () => {
    expect(activeStepId(initialNavigation)).toBeNull()
    const advanced = run([{ type: 'next', choice: choice('a') }])
    expect(activeStepId(advanced)).toBe('a')
    expect(activeStepId(navigationReducer(advanced, { type: 'select', stepId: 'a.1' }))).toBe('a.1')
  })
})
