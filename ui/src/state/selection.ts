export interface Selection {
  project: string | null
  objectId: string | null
  columnId: string | null
}

export type SelectionAction =
  | { type: 'project'; value: string | null }
  | { type: 'object'; value: string | null }
  | { type: 'column'; value: string | null }

export const emptySelection: Selection = { project: null, objectId: null, columnId: null }

// Changing a selector clears everything below it; re-selecting the same value changes nothing.
export function selectionReducer(state: Selection, action: SelectionAction): Selection {
  switch (action.type) {
    case 'project':
      return action.value === state.project ? state : { project: action.value, objectId: null, columnId: null }
    case 'object':
      return action.value === state.objectId ? state : { ...state, objectId: action.value, columnId: null }
    case 'column':
      return action.value === state.columnId ? state : { ...state, columnId: action.value }
  }
}
