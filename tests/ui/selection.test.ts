import { emptySelection, selectionReducer, type Selection } from '../../ui/src/state/selection'

const full: Selection = { project: 'P', objectId: 'O', columnId: 'C' }

describe('selectionReducer', () => {
  it('starts empty', () => {
    expect(emptySelection).toEqual({ project: null, objectId: null, columnId: null })
  })

  it('selecting a project clears object and column', () => {
    expect(selectionReducer(full, { type: 'project', value: 'Q' })).toEqual({ project: 'Q', objectId: null, columnId: null })
  })

  it('selecting an object keeps the project and clears the column', () => {
    expect(selectionReducer(full, { type: 'object', value: 'O2' })).toEqual({ project: 'P', objectId: 'O2', columnId: null })
  })

  it('selecting a column changes only the column', () => {
    expect(selectionReducer(full, { type: 'column', value: 'C2' })).toEqual({ project: 'P', objectId: 'O', columnId: 'C2' })
  })

  it('re-selecting the same value keeps the same state object', () => {
    expect(selectionReducer(full, { type: 'project', value: 'P' })).toBe(full)
    expect(selectionReducer(full, { type: 'object', value: 'O' })).toBe(full)
    expect(selectionReducer(full, { type: 'column', value: 'C' })).toBe(full)
  })

  it('clearing a selector clears everything below it', () => {
    expect(selectionReducer(full, { type: 'project', value: null })).toEqual(emptySelection)
    expect(selectionReducer(full, { type: 'object', value: null })).toEqual({ project: 'P', objectId: null, columnId: null })
  })
})
