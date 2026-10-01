import { useEffect, useState } from 'react'
import { getRuns, RAGGUARD_TENANT_ID } from '../api/client'
import { Section } from '../components/Cards'
import '../styles/recovery.css'

type Run = {
  id: string
  query: string
  status: string
  method?: string
  latency_ms?: number
  created_at: string
  source?: string
  application_id?: string
  environment?: string
  retrieved_count?: number
  top_score?: number | null
  failure_type?: string | null
  recovery_status?: string | null
}

const pageSize = 50
const refreshMs = 4000

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

function outcomeClass(status: string) {
  if (['healthy', 'grounded', 'promoted'].includes(status)) return 'promoted'
  if (['escalated', 'failure', 'no_match'].includes(status)) return 'escalated'
  return 'rolled_back'
}

export default function Runs() {
  const [runs, setRuns] = useState<Run[]>([])
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)

  useEffect(() => {
    let active = true
    const refresh = async (initial = false) => {
      if (initial) setLoading(true)
      try {
        const result = await getRuns(pageSize, page * pageSize)
        if (active) {
          setRuns(result)
          setError('')
          setUpdatedAt(new Date())
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : 'Runs unavailable')
      } finally {
        if (active && initial) setLoading(false)
      }
    }
    void refresh(true)
    const timer = window.setInterval(() => { void refresh() }, refreshMs)
    return () => { active = false; window.clearInterval(timer) }
  }, [page, refreshKey])

  return <div className="page operations-page">
    <div className="recoveries-heading">
      <div>
        <span className="recovery-eyebrow">RAGGUARD ACTIVITY</span>
        <h2>Query runs</h2>
      </div>
      <button className="ghost recovery-refresh" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}>
        Refresh
      </button>
    </div>
    <Section title={`Activity · ${page * pageSize + runs.length}${runs.length === pageSize ? '+' : ''}`}>
      {error && <div className="recovery-error" role="alert">{error}</div>}
      <p className="operations-note">RAGGuard tenant: <strong>{RAGGUARD_TENANT_ID || 'API service tenant'}</strong>. Updates every {refreshMs / 1000} seconds.{updatedAt ? ` Last checked ${updatedAt.toLocaleTimeString()}.` : ''}</p>
      {loading ? <p className="operations-note">Loading activity…</p> : runs.length ? <>
        <div className="operations-table-wrap">
          <table className="operations-table">
            <thead><tr>
              <th>Time</th><th>Query</th><th>Application</th><th>Outcome</th>
              <th>Method</th><th>Chunks</th><th>Top score</th><th>Latency</th>
            </tr></thead>
            <tbody>{runs.map((run) => <tr key={`${run.source || 'workspace'}:${run.id}`}>
              <td>{formatDate(run.created_at)}</td>
              <td>{run.query}</td>
              <td>{run.application_id || 'RAGGuard'}{run.environment ? ` · ${run.environment}` : ''}</td>
              <td><span className={`recovery-pill ${outcomeClass(run.status)}`}>{run.status}</span>
                {run.failure_type && <small> · {run.failure_type}</small>}</td>
              <td>{run.method || '--'}</td>
              <td>{run.retrieved_count ?? '--'}</td>
              <td>{typeof run.top_score === 'number' ? run.top_score.toFixed(3) : '--'}</td>
              <td>{typeof run.latency_ms === 'number' ? `${Math.round(run.latency_ms)} ms` : '--'}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="recovery-pagination">
          <button className="ghost" onClick={() => setPage((value) => Math.max(0, value - 1))} disabled={page === 0}>Newer</button>
          <span>Page {page + 1}</span>
          <button className="ghost" onClick={() => setPage((value) => value + 1)} disabled={runs.length < pageSize}>Older</button>
        </div>
      </> : <p className="operations-empty">No query activity has been recorded.</p>}
    </Section>
  </div>
}
