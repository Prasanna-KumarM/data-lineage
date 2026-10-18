import { useCallback, useMemo, useSyncExternalStore } from 'react'

export type Route =
  | { name: 'summary'; project: string | null; objectId: string | null }
  | { name: 'lineage'; project: string | null; objectId: string | null; columnId: string | null }

const decode = (part: string | undefined) => (part ? decodeURIComponent(part) : null)

/** Hash routes: #/summary[/project[/object]] and #/lineage[/project[/object[/column]]]. */
export function parseHash(hash: string): Route {
  const [page, project, objectId, columnId] = hash.replace(/^#\/?/, '').split('/')
  if (page === 'lineage') {
    return { name: 'lineage', project: decode(project), objectId: decode(objectId), columnId: decode(columnId) }
  }
  return { name: 'summary', project: decode(project), objectId: decode(objectId) }
}

export function formatRoute(route: Route): string {
  const parts: string[] = [route.name]
  const ids = route.name === 'lineage' ? [route.project, route.objectId, route.columnId] : [route.project, route.objectId]
  for (const id of ids) {
    if (!id) break
    parts.push(encodeURIComponent(id))
  }
  return `#/${parts.join('/')}`
}

function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener)
  return () => window.removeEventListener('hashchange', listener)
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  return useMemo(() => parseHash(hash), [hash])
}

/** Moves to a page and keeps it in the browser history. */
export function useNavigate() {
  return useCallback((route: Route) => {
    window.location.hash = formatRoute(route)
  }, [])
}

/** Keeps the address in step with what is shown, without adding a history entry. */
export function replaceRoute(route: Route) {
  const next = formatRoute(route)
  if (window.location.hash !== next) window.history.replaceState(null, '', next)
}
