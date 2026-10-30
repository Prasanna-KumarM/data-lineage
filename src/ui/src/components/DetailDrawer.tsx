import { useEffect, useRef } from 'react'
import { ApiError, type ApiClient } from '../api/client'
import type { Endpoint, StepDetail } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { ConfidenceBadge, RelationBadge } from './Badges'

interface Props {
  client: ApiClient
  stepId: string
  developer: boolean
  onDeveloperChange: (value: boolean) => void
  onClose: () => void
}

const endpointText = (e: Endpoint) => `${e.object_name ?? '?'}.${e.column_name ?? '?'}`

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  )
}

function Body({ detail, developer }: { detail: StepDetail; developer: boolean }) {
  const hasExpression = Boolean(detail.expression_id || detail.driving_expression || detail.result_expression)
  const reason = detail.confidence.reason ?? detail.confidence.reason_code
  return (
    <>
      <section className="drawer-section" aria-label="Mapping">
        <h3>Mapping</h3>
        <p className="drawer-flow">
          <span className="drawer-endpoint">{endpointText(detail.source)}</span>
          <span aria-hidden="true"> → </span>
          <span className="drawer-endpoint">{endpointText(detail.target)}</span>
        </p>
        <p>
          <RelationBadge type={detail.relation_type} />
        </p>
        <dl className="facts">
          <Row label="Component">{detail.component.component_name ?? '—'}</Row>
          <Row label="Business process">{detail.business_process.business_process_name ?? '—'}</Row>
          {detail.traversal_path && <Row label="Traversal path">{detail.traversal_path}</Row>}
        </dl>
      </section>

      <section className="drawer-section" aria-label="Confidence">
        <h3>Confidence</h3>
        <p>
          <ConfidenceBadge value={detail.confidence.confidence_class} />
        </p>
        {reason && <p className="drawer-reason">{reason}</p>}
      </section>

      {detail.persistence && (
        <section className="drawer-section" aria-label="Persistence">
          <h3>Persistence</h3>
          <p className="callout not-persisted">
            <strong>{detail.persistence.status}</strong>
            {(detail.persistence.reason ?? detail.persistence.reason_code) && (
              <span> · {detail.persistence.reason ?? detail.persistence.reason_code}</span>
            )}
          </p>
        </section>
      )}

      {hasExpression && (
        <section className="drawer-section" aria-label="Expression">
          <h3>Expression</h3>
          <div className="expr-block when">
            <span className="expr-tag when">Condition · when</span>
            <code>{detail.driving_expression ?? '—'}</code>
          </div>
          <div className="expr-block value">
            <span className="expr-tag value">Value · result</span>
            <code>{detail.result_expression ?? '—'}</code>
          </div>
        </section>
      )}

      {detail.dependencies.length > 0 && (
        <section className="drawer-section" aria-label="Operands">
          <h3>Operands</h3>
          <ol className="operands">
            {detail.dependencies.map((d, i) => (
              <li key={`${d.operand_order}-${i}`}>
                {endpointText(d)}
                {d.object_type && <span className="card-meta"> · {d.object_type}</span>}
              </li>
            ))}
          </ol>
        </section>
      )}

      {(detail.contributors?.length ?? 0) > 1 && (
        <section className="drawer-section" aria-label="Contributing mappings">
          <h3>Contributing mappings</h3>
          <p className="card-meta">
            This path is populated by {detail.contributors!.length} mappings:
          </p>
          <ol className="operands">
            {detail.contributors!.map((c) => (
              <li key={c.relation_id}>
                <RelationBadge type={c.relation_type} /> {c.component_name ?? 'No component'}
                {c.business_process_name && <span className="card-meta"> · {c.business_process_name}</span>}
                {c.driving_expression && <div className="card-meta">when {c.driving_expression}</div>}
                {c.result_expression && <div className="card-meta">Value {c.result_expression}</div>}
              </li>
            ))}
          </ol>
        </section>
      )}

      {developer && (
        <section className="drawer-section developer" aria-label="Developer details">
          <h3>Developer details</h3>
          <dl className="facts">
            <Row label="Step ID">{detail.step_id}</Row>
            <Row label="Relation ID">{detail.relation_id}</Row>
            <Row label="Expression ID">{detail.expression_id ?? '—'}</Row>
            <Row label="Path ID">{detail.path_id}</Row>
            <Row label="Level">{detail.lineage_level}</Row>
            <Row label="Hop count">{detail.hop_count ?? '—'}</Row>
            <Row label="Steps using this relation">{detail.step_ids.length}</Row>
            <Row label="Component ID">{detail.component.component_id ?? '—'}</Row>
            <Row label="Component type">{detail.component.component_type ?? '—'}</Row>
            <Row label="Business process ID">{detail.business_process.business_process_id ?? '—'}</Row>
            <Row label="Source object ID">{detail.source.object_id ?? '—'}</Row>
            <Row label="Source column ID">{detail.source.column_id ?? '—'}</Row>
            <Row label="Source object type">{detail.source.object_type ?? '—'}</Row>
            <Row label="Target object ID">{detail.target.object_id ?? '—'}</Row>
            <Row label="Target column ID">{detail.target.column_id ?? '—'}</Row>
            <Row label="Confidence reason code">{detail.confidence.reason_code ?? '—'}</Row>
          </dl>
        </section>
      )}
    </>
  )
}

/** Side drawer with the full detail of one mapping; it does not touch the navigation state. */
export function DetailDrawer({ client, stepId, developer, onDeveloperChange, onClose }: Props) {
  const detail = useAsync<StepDetail>((signal) => client.stepDetail(stepId, signal), `detail:${stepId}`)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()
  }, [stepId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <aside className="drawer" role="dialog" aria-modal="false" aria-labelledby="drawer-title">
      <header className="drawer-head">
        <h2 id="drawer-title">Mapping details</h2>
        <button ref={closeRef} type="button" className="drawer-close" aria-label="Close details" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="drawer-body">
        {detail.status === 'loading' && (
          <p className="status" role="status">
            Loading details…
          </p>
        )}
        {detail.status === 'error' && (
          <p className="status error" role="alert">
            {detail.error instanceof ApiError ? detail.error.message : 'Something went wrong.'}{' '}
            <button type="button" onClick={detail.reload}>
              Retry
            </button>
          </p>
        )}
        {detail.status === 'success' && <Body detail={detail.data} developer={developer} />}
      </div>
      <footer className="drawer-foot">
        <label>
          <input type="checkbox" checked={developer} onChange={(e) => onDeveloperChange(e.target.checked)} /> Show developer
          details
        </label>
      </footer>
    </aside>
  )
}
