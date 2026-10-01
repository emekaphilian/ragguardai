import { useEffect, useMemo, useState } from 'react'
import { getRecoveries, getRecovery } from '../api/client'
import { Section } from '../components/Cards'
import type { RecoveryAuditEvent, RecoveryAuditRecord } from '../types'
import '../styles/recovery.css'
import '../styles/recovery-pagination.css'

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
        const matchesStatus = initialStatusFilter === 'all' || record.final_status === initialStatusFilter
        const query = initialSearch.trim().toLowerCase()
        const matchesQuery = !query || [
          record.recovery_id,
          record.failure_type,
          record.application_id,
          record.environment,
          record.tenant_id,
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
      if (statusFilter !== 'all' && record.final_status !== statusFilter) return false
      if (!query) return true
      return [
        record.recovery_id,
        record.failure_type,
        record.application_id,
        record.environment,
        record.tenant_id,
        record.ragguard_tenant_id,
        record.final_status,
      ].some((value) => value?.toLowerCase().includes(query))
    })
  }, [records, search, statusFilter])

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

  return (
    <div className="page recoveries-page">
      <div className="recoveries-heading">
        <div>
          <span className="recovery-eyebrow">RECOVERY AUDIT</span>
          <h2>Recovery runs</h2>
          <p>Inspect decisions, repair attempts, validation, and terminal outcomes.</p>
        </div>
        <button className="ghost recovery-refresh" onClick={() => void refresh()} disabled={loading} title="Refresh recovery records">
          <span aria-hidden="true">↻</span> Refresh
        </button>
      </div>

      {error && <div className="recovery-error" role="alert">{error}</div>}

      <div className="recovery-workspace">
        <Section title={`Runs · ${total}`}>
          <div className="recovery-filters">
            <label className="recovery-search">
              <span>Search this page</span>
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="ID, failure, app, tenant" />
            </label>
            <label>
              <span>Outcome</span>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="all">All outcomes</option>
                <option value="promoted">Promoted</option>
                <option value="rolled_back">Rolled back</option>
                <option value="escalated">Escalated</option>
              </select>
            </label>
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
                  <span className={`recovery-dot ${record.final_status}`} />
                  <span className="recovery-list-copy">
                    <strong>{label(record.failure_type || 'recovery')}</strong>
                    <small>
                      {record.application_id || 'Unknown app'} · {record.environment || 'Unknown environment'}
                      {' · Source tenant: '}{record.tenant_id || 'unknown'}
                    </small>
                  </span>
                  <span className={`recovery-pill ${record.final_status}`}>{label(record.final_status)}</span>
                  <span className="recovery-list-meta">{record.attempts.length} attempts · {formatDuration(record)}</span>
                  <time>{formatDate(record.started_at)}</time>
                </button>
              ))}
            </div>
          ) : (
            <div className="recovery-empty">
              <span aria-hidden="true">◷</span>
              <strong>{total > 0 ? 'No matching recoveries on this page' : 'No recovery runs yet'}</strong>
              <p>{total > 0 ? 'Change the search or outcome filter.' : 'Failed observations will appear here after the recovery workflow records an audit.'}</p>
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
                <span className={`recovery-pill ${selected.final_status}`}>{label(selected.final_status)}</span>
              </div>
              <dl className="recovery-facts">
                <div><dt>Graph run</dt><dd>{selected.graph_run_id}</dd></div>
                <div><dt>Failure ID</dt><dd>{selected.failure_id || '--'}</dd></div>
                <div><dt>Application</dt><dd>{selected.application_id || '--'}</dd></div>
                <div><dt>Environment</dt><dd>{selected.environment || '--'}</dd></div>
                <div><dt>External source tenant</dt><dd>{selected.tenant_id || '--'}</dd></div>
                <div><dt>RAGGuard access tenant</dt><dd>{selected.ragguard_tenant_id || '--'}</dd></div>
                <div><dt>Duration</dt><dd>{formatDuration(selected)}</dd></div>
              </dl>
              <div className="recovery-scoreline">
                <span>Original <strong>{score(selected.original_score)}</strong></span>
                <span>Final <strong>{score(selected.final_score)}</strong></span>
                <span>Change <strong>{selected.improvement == null ? '--' : `${selected.improvement > 0 ? '+' : ''}${selected.improvement.toFixed(3)}`}</strong></span>
              </div>
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
