import type { Choice } from '../api/types'

export interface NavigationState {
  /** Steps the user has advanced through, in order; each is one completed hop. */
  path: Choice[]
  /** Highlighted choice in the current list; not yet advanced into. */
  selectedStepId: string | null
}

export type NavigationAction =
  | { type: 'select'; stepId: string | null }
  | { type: 'next'; choice: Choice }
  | { type: 'back' }
  | { type: 'jump'; depth: number }

export const initialNavigation: NavigationState = { path: [], selectedStepId: null }

// Going back or jumping restores the selection that led out of that level.
export function navigationReducer(state: NavigationState, action: NavigationAction): NavigationState {
  switch (action.type) {
    case 'select':
      return action.stepId === state.selectedStepId ? state : { ...state, selectedStepId: action.stepId }
    case 'next':
      return { path: [...state.path, action.choice], selectedStepId: null }
    case 'back': {
      const last = state.path[state.path.length - 1]
      return last ? { path: state.path.slice(0, -1), selectedStepId: last.step_id } : state
    }
    case 'jump': {
      if (action.depth < 0 || action.depth >= state.path.length) return state
      return { path: state.path.slice(0, action.depth), selectedStepId: state.path[action.depth].step_id }
    }
  }
}

/** The step whose branch is being followed: the highlighted choice, else the last hop taken. */
export function activeStepId(state: NavigationState): string | null {
  return state.selectedStepId ?? state.path[state.path.length - 1]?.step_id ?? null
}
