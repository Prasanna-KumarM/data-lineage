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

  // Business/developer audience for the summary landing page; the toggle sits in the topbar.
  const [audience, setAudience] = useState<'business' | 'developer' | null>(null)
  const [catalogAvailable, setCatalogAvailable] = useState(false)
  // Project/catalog notes reported by the summary page; the info icon sits in the topbar.
  const [notes, setNotes] = useState<string[]>([])
  const [notesOpen, setNotesOpen] = useState(false)
  useEffect(() => {
    const onChange = () => setNavigations((n) => n + 1)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return (
    <div
      className={
        route.name === 'lineage' ? 'app app-lineage' : route.name === 'summary' && route.objectId ? 'app app-table' : 'app'
      }
    >
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
        {route.name === 'summary' && !route.objectId && catalogAvailable && audience !== null && (
          <div className="view-toggle topbar-toggle" role="group" aria-label="Audience">
            <button type="button" aria-pressed={audience === 'business'} onClick={() => setAudience('business')}>
              Business
            </button>
            <button type="button" aria-pressed={audience === 'developer'} onClick={() => setAudience('developer')}>
              Developer
            </button>
          </div>
        )}
        {route.name === 'summary' && notes.length > 0 && (
          <div className="info-anchor">
            <button
              type="button"
              className="info-toggle"
              aria-expanded={notesOpen}
              aria-label={`${notes.length} ${notes.length === 1 ? 'note' : 'notes'} about the listed projects`}
              title="Notes about the listed projects"
              onClick={() => setNotesOpen((open) => !open)}
            >
              <span aria-hidden="true">ⓘ</span>
            </button>
            {notesOpen && (
              <ul className="info-notes info-dropdown">
                {notes.map((note) => (
                  <li key={note} className="status note">
                    {note}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </header>
      {route.name === 'lineage' ? (
        <LineagePage key={navigations} client={client} route={route} />
      ) : (
        <SummaryPage
          client={client}
          route={route}
          audience={audience}
          onAudienceChange={setAudience}
          onCatalogAvailable={setCatalogAvailable}
          onNotesChange={setNotes}
        />
      )}
    </div>
  )
}
