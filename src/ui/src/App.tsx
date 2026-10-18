import { useEffect, useMemo, useState } from 'react'
import { createApiClient, newSessionId, type ApiClient } from './api/client'
import { LineagePage } from './pages/LineagePage'
import { SummaryPage } from './pages/SummaryPage'
import { useRoute } from './routing'

interface Props {
  client?: ApiClient
}

export default function App({ client: injected }: Props) {
  const client = useMemo(() => injected ?? createApiClient({ sessionId: newSessionId() }), [injected])
  const route = useRoute()

  // Counts real navigations only; the walkthrough rewriting its own address must not restart it.
  const [navigations, setNavigations] = useState(0)
  useEffect(() => {
    const onChange = () => setNavigations((n) => n + 1)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <h1>Data Lineage</h1>
        <nav aria-label="Pages">
          <a href="#/summary" aria-current={route.name === 'summary' ? 'page' : undefined}>
            Summary
          </a>
          <a href="#/lineage" aria-current={route.name === 'lineage' ? 'page' : undefined}>
            Walkthrough
          </a>
        </nav>
      </header>
      {route.name === 'lineage' ? (
        <LineagePage key={navigations} client={client} route={route} />
      ) : (
        <SummaryPage client={client} route={route} />
      )}
    </div>
  )
}
