import { useEffect, useMemo, useState } from 'react'
import { getRecoveries, getRecovery } from '../api/client'
import { Section } from '../components/Cards'
import type { RecoveryAuditEvent, RecoveryAuditRecord } from '../types'
import '../styles/recovery.css'
import '../styles/recovery-pagination.css'
import '../styles/recovery-audit.css'
import '../styles/recovery-outcome-guide.css'

function formatDate(value: string | null | undefined) {
  if (!value) return 'In progress'
  return new Date(value).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatDuration(record: RecoveryAuditRecord) {
  if (!record.completed_at) return 'In progress'
  const elapsed = Math.max(
    0,
    new Date(record.completed_at).getTime() - new Date(record.started_at).getTime(),
  )
  return elapsed < 1000 ? `${elapsed} ms` : `${(elapsed / 1000).toFixed(2)} s`
}

function label(value: string) {
  return value.replace(/_/g, ' ')
}

function score(value: number | null | undefined) {
  return typeof value === 'number' ? value.toFixed(3) : '--'
}

function isInProgress(record: RecoveryAuditRecord) {
  return !record.completed_at || record.final_status === 'running'
}

function outcomeClass(record: RecoveryAuditRecord) {
  return isInProgress(record) ? 'running' : record.final_status
}

function outcomeLabel(record: RecoveryAuditRecord) {
  return isInProgress(record) ? 'In progress' : label(record.final_status)
}

function retrievalStat(stats: Record<string, unknown> | undefined, key: string) {
  const value = stats?.[key]
  return typeof value === 'number' ? value : '--'
}

function EventDetail({ event }: { event: RecoveryAuditEvent }) {
  return (
    <div className="timeline-event-detail">
      {event.reason && <p>{event.reason}</p>}
      {event.strategy && <p>Strategy: <strong>{label(event.strategy)}</strong></p>}
      {event.attempt && <p>Attempt {event.attempt}</p>}
      {(event.before_score !== null && event.before_score !== undefined) && (
        <p>Score: {score(event.before_score)} → {score(event.after_score)}</p>
      )}
      {event.improvement !== null && event.improvement !== undefined && (
        <p>Change: {event.improvement > 0 ? '+' : ''}{event.improvement.toFixed(3)}</p>
      )}
      {event.validation_valid !== null && event.validation_valid !== undefined && (
        <p>Validation: {event.validation_valid ? 'valid' : 'invalid'} · {event.validation_improved ? 'improved' : 'not improved'}</p>
      )}
      <time>{formatDate(event.timestamp)}</time>
    </div>
  )
}

export default function Recoveries({ initialSearch = '', initialStatusFilter = 'all' }: { initialSearch?: string; initialStatusFilter?: string }) {
  const [records, setRecords] = useState<RecoveryAuditRecord[]>([])
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [selected, setSelected] = useState<RecoveryAuditRecord | null>(null)
  const [page, setPage] = useState(1)
  const pageSize = 50
  const [statusFilter, setStatusFilter] = useState(initialStatusFilter)
  const [attemptFilter, setAttemptFilter] = useState('all')
  const [search, setSearch] = useState(initialSearch)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      const loaded = await getRecoveries(page, pageSize)
      setRecords(loaded.items)
      setTotal(loaded.total)
      setHasNext(loaded.has_next)
      const matchesInitialSelection = (record: RecoveryAuditRecord) => {
        const matchesStatus = initialStatusFilter === 'all'
          || (initialStatusFilter === 'running' ? isInProgress(record) : record.final_status === initialStatusFilter)
        const query = initialSearch.trim().toLowerCase()
        const matchesQuery = !query || [
          record.recovery_id,
          record.failure_type,
          record.application_id,
          record.environment,
          record.final_status,
        ].some((value) => value?.toLowerCase().includes(query))
        return matchesStatus && matchesQuery
      }
      if (selected) {
        const current = loaded.items.find((record) => record.recovery_id === selected.recovery_id)
        if (current && matchesInitialSelection(current)) setSelected(current)
        else setSelected(loaded.items.find(matchesInitialSelection) || loaded.items[0] || null)
      } else if (loaded.items.length) {
        setSelected(loaded.items.find(matchesInitialSelection) || loaded.items[0])
      } else {
        setSelected(null)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load recovery records')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [page])

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return records.filter((record) => {
      if (statusFilter !== 'all' && (statusFilter === 'running' ? !isInProgress(record) : record.final_status !== statusFilter)) return false
      if (attemptFilter === 'attempted' && record.attempts.length === 0) return false
      if (attemptFilter === 'not_attempted' && record.attempts.length > 0) return false
      if (!query) return true
      return [
        record.recovery_id,
        record.failure_type,
        record.application_id,
        record.environment,
        record.ragguard_tenant_id,
        record.final_status,
      ].some((value) => value?.toLowerCase().includes(query))
    })
  }, [records, search, statusFilter, attemptFilter])

  const openRecord = async (record: RecoveryAuditRecord) => {
    setSelected(record)
    setDetailLoading(true)
    try {
      setSelected(await getRecovery(record.recovery_id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load recovery detail')
    } finally {
      setDetailLoading(false)
    }
  }

  const runningOnPage = records.filter(isInProgress).length
  const attemptedOnPage = records.filter((record) => record.attempts.length > 0).length
  const planEvent = selected?.events.find((event) => event.event_type === 'repair_planned')

  return (
    <div className="page recoveries-page">
      <div className="recoveries-heading">
        <div>
          <span className="recovery-eyebrow">RECOVERY AUDIT</span>
          <h2>Recovery audit</h2>
          <p>Query Runs show observed requests. This audit shows recovery workflow records: repair attempts, detection-only escalations, and work still in progress. One request may have no recovery record, and historical or incomplete records may not represent a new failure.</p>
        </div>
        <button className="ghost recovery-refresh" onClick={() => void refresh()} disabled={loading} title="Refresh recovery records">
          <span aria-hidden="true">↻</span> Refresh
        </button>
      </div>

      {error && <div className="recovery-error" role="alert">{error}</div>}

      <div className="recovery-outcome-guide" aria-label="Recovery outcome definitions">
        <div><strong>Promoted</strong><span>Validation accepted an improvement; the repaired result was used.</span></div>
        <div><strong>Rolled back</strong><span>The repair failed validation; the original result was retained.</span></div>
        <div><strong>Escalated</strong><span>No safe repair was accepted; RAGGuard did not mark the failure fixed.</span></div>
      </div>

      <div className="recovery-workspace">
        <Section title={`Recovery audit records · ${total}`}>
          <div className="recovery-filters">
            <label className="recovery-search">
              <span>Search this page</span>
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="ID, failure, application, environment" />
            </label>
            <label>
              <span>Outcome</span>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">All outcomes</option>
                <option value="promoted">Promoted</option>
                <option value="rolled_back">Rolled back</option>
                <option value="escalated">Escalated</option>
                <option value="running">In progress</option>
              </select>
            </label>
            <label>
              <span>Repair attempts</span>
              <select value={attemptFilter} onChange={(event) => setAttemptFilter(event.target.value)}>
                <option value="all">All records</option>
                <option value="attempted">Attempted</option>
                <option value="not_attempted">None attempted</option>
              </select>
            </label>
          </div>

          <div className="recovery-audit-summary">
            <span>{records.length} records on this page</span>
            <span>{runningOnPage} in progress</span>
            <span>{attemptedOnPage} with attempts</span>
            <span>{records.length - attemptedOnPage} with none attempted</span>
          </div>

          {loading ? (
            <p className="recovery-muted">Loading recovery records…</p>
          ) : filtered.length ? (
            <div className="recovery-list" role="list">
              {filtered.map((record) => (
                <button
                  type="button"
                  role="listitem"
                  className={`recovery-list-row ${selected?.recovery_id === record.recovery_id ? 'selected' : ''}`}
                  key={record.recovery_id}
                  onClick={() => void openRecord(record)}
                >
                  <span className={`recovery-dot ${outcomeClass(record)}`} />
                  <span className="recovery-list-copy">
                    <strong>{label(record.failure_type || 'recovery')}</strong>
                    <small>
                      {record.application_id || 'Unknown app'} · {record.environment || 'Unknown environment'}
                      {' · RAGGuard tenant: '}{record.ragguard_tenant_id || 'unknown'}
                    </small>
                  </span>
                  <span className={`recovery-pill ${outcomeClass(record)}`}>{outcomeLabel(record)}</span>
                  <span className="recovery-list-meta">
                    {record.attempts.length > 0
                      ? `${record.attempts.length} repair attempts`
                      : record.final_status === 'running'
                        ? 'No repair attempt recorded yet'
                        : 'Detection only · no repair attempt'}
                    {' · '}{formatDuration(record)}
                  </span>
                  <time>{formatDate(record.started_at)}</time>
                </button>
              ))}
            </div>
          ) : (
            <div className="recovery-empty">
              <span aria-hidden="true">◷</span>
              <strong>{total > 0 ? 'No matching recovery records on this page' : 'No recovery audit records yet'}</strong>
              <p>{total > 0 ? 'Change the search, outcome, or attempt filter.' : 'Failed observations appear here when the recovery workflow creates an audit record.'}</p>
            </div>
          )}
          <div className="recovery-pagination">
            <span>Page {page} of {Math.max(1, Math.ceil(total / pageSize))} · {total} total</span>
            <div>
              <button className="ghost" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1 || loading}>
                Previous
              </button>
              <button className="ghost" onClick={() => setPage((current) => current + 1)} disabled={!hasNext || loading}>
                Next
              </button>
            </div>
          </div>
        </Section>

        <Section title="Recovery timeline">
          {detailLoading ? (
            <p className="recovery-muted">Loading event detail…</p>
          ) : selected ? (
            <div className="recovery-detail">
              <div className="recovery-detail-top">
                <div>
                  <span className="recovery-eyebrow">{selected.recovery_id}</span>
                  <h3>{label(selected.failure_type || 'recovery')}</h3>
                </div>
                <span className={`recovery-pill ${outcomeClass(selected)}`}>{outcomeLabel(selected)}</span>
              </div>
              <dl className="recovery-facts">
                <div><dt>Graph run</dt><dd>{selected.graph_run_id}</dd></div>
                <div><dt>Failure ID</dt><dd>{selected.failure_id || '--'}</dd></div>
                <div><dt>Application</dt><dd>{selected.application_id || '--'}</dd></div>
                <div><dt>Environment</dt><dd>{selected.environment || '--'}</dd></div>
                <div><dt>RAGGuard access tenant</dt><dd>{selected.ragguard_tenant_id || '--'}</dd></div>
                <div><dt>Duration</dt><dd>{formatDuration(selected)}</dd></div>
              </dl>
              <section className="recovery-evidence">
                <h4>Original request</h4>
                <p className="recovery-original-query">{selected.query || 'Original query was not captured for this record.'}</p>
                <div className="recovery-evidence-heading">
                  <strong>Initial retrieval</strong>
                  <span>{selected.retrieved_chunks?.length ?? 0} chunks · {selected.retrieval_method || 'method not recorded'}</span>
                </div>
                {selected.embedding_degraded !== null && selected.embedding_degraded !== undefined && (
                  <small className="recovery-muted">Embedding degraded: {selected.embedding_degraded ? 'Yes' : 'No'}</small>
                )}
                {selected.retrieved_chunks?.length ? <ul className="recovery-chunk-list">
                  {selected.retrieved_chunks.map((chunk, index) => <li key={`${chunk.id}:${index}`}>
                    <code>{chunk.id}</code><span>score {score(chunk.score)}</span>
                  </li>)}
                </ul> : <p className="recovery-muted">No retrieved chunks were recorded in the initial snapshot.</p>}
              </section>
              <div className="recovery-scoreline">
                <span>Original evaluation score <strong>{score(selected.original_score)}</strong></span>
                <span>Final evaluation score <strong>{score(selected.final_score)}</strong></span>
                <span>Change <strong>{selected.improvement == null ? '--' : `${selected.improvement > 0 ? '+' : ''}${selected.improvement.toFixed(3)}`}</strong></span>
              </div>
              <section className="recovery-attempt-section">
                <div className="recovery-evidence-heading"><h4>Repair attempts</h4><span>{selected.attempts.length}</span></div>
                {selected.attempts.length ? selected.attempts.map((attempt, index) => {
                  const validation = selected.events.find((event) => (
                    event.event_type === 'validation_completed' && event.attempt === index + 1
                  ))
                  const before = validation?.metadata?.before_retrieval as Record<string, unknown> | undefined
                  const after = validation?.metadata?.after_retrieval as Record<string, unknown> | undefined
                  return <article className="recovery-attempt-detail" key={`${attempt.strategy}:${index}`}>
                    <strong>Attempt {index + 1} · {label(attempt.strategy)}</strong>
                    <span>Outcome: {label(attempt.status)} · score change {attempt.improvement == null ? '--' : `${attempt.improvement > 0 ? '+' : ''}${attempt.improvement.toFixed(3)}`}</span>
                    {(before || after) && <small>Retrieved: {retrievalStat(before, 'retrieved_chunks')} → {retrievalStat(after, 'retrieved_chunks')} · unique: {retrievalStat(before, 'unique_chunks')} → {retrievalStat(after, 'unique_chunks')} · duplicates: {retrievalStat(before, 'duplicate_chunks')} → {retrievalStat(after, 'duplicate_chunks')}</small>}
                    {validation && <small>Validation: {validation.validation_valid ? 'valid' : 'invalid'} · {validation.validation_improved ? 'improved' : 'not improved'}</small>}
                  </article>
                }) : <div className="recovery-no-attempt">
                  <strong>No repair attempt was recorded.</strong>
                  <small>{planEvent?.reason || (isInProgress(selected) ? 'No strategy has started yet.' : 'The failure was recorded without an applicable repair strategy.')}</small>
                </div>}
              </section>
              {!isInProgress(selected) && selected.final_status === 'promoted' && <p className="recovery-outcome-note promoted-note">The repair passed configured validation and was accepted as an improvement. This does not certify that the final answer is factually correct.</p>}
              {!isInProgress(selected) && selected.final_status === 'rolled_back' && <p className="recovery-outcome-note rollback-note">The repair did not pass validation; the original retrieval was retained.</p>}
              {!isInProgress(selected) && selected.final_status === 'escalated' && <p className="recovery-outcome-note escalation-note">RAGGuard escalated rather than marking the problem as repaired.</p>}
              {isInProgress(selected) && <p className="recovery-outcome-note running-note">This record has not reached a terminal outcome; attempt count and duration may be incomplete.</p>}
              <div className="recovery-timeline">
                {selected.events.map((event) => (
                  <article className="timeline-event" key={event.event_id}>
                    <span className={`timeline-marker ${event.event_type}`} />
                    <div className="timeline-event-body">
                      <div className="timeline-event-heading">
                        <strong>{label(event.event_type)}</strong>
                        {event.status && <span>{label(event.status)}</span>}
                      </div>
                      <EventDetail event={event} />
                    </div>
                  </article>
                ))}
              </div>
            </div>
          ) : (
            <div className="recovery-empty compact">
              <span aria-hidden="true">↖</span>
              <strong>Select a recovery run</strong>
              <p>Its audit events and before/after scores will appear here.</p>
            </div>
          )}
        </Section>
      </div>
    </div>
  )
}
