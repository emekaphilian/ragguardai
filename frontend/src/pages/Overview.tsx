import { useEffect, useState } from 'react'
import NarratorPanel from '../components/NarratorPanel'
import { MetricCard, Section } from '../components/Cards'
import { getDashboard } from '../api/client'

const REFRESH_MS = 4000
const percent = (value: unknown) => typeof value === 'number' ? `${Math.round(value * 100)}%` : '—'
const qualityStatus = (value: unknown) => typeof value !== 'number' ? 'neutral' : value >= 0.75 ? 'good' : value >= 0.5 ? 'warn' : 'bad'

export default function Overview() {
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const refresh = () => getDashboard()
      .then((result) => { if (active) { setData(result); setError('') } })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Dashboard unavailable') })
    void refresh()
    const timer = window.setInterval(refresh, REFRESH_MS)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  if (error && !data) return <div className="page"><Section title="Connection unavailable"><p className="answer">{error}. Start the API to view activity.</p></Section></div>
  if (!data) return <div className="page">Loading live activity…</div>

  const metrics = data.metrics || {}
  const hasWorkspaceQuality = typeof metrics.overall_quality === 'number'
  const recentRuns = data.recent_runs || []

  return <div className="page">
    <NarratorPanel page="Overview" data={metrics} />
    {error && <p className="activity-error" role="status">Refresh failed: {error}. Showing the last successful update.</p>}
    <div className="metrics">
      <MetricCard label="Queries run" value={String(metrics.total_runs ?? 0)} status={metrics.total_runs ? 'good' : 'neutral'} />
      <MetricCard label="TrustAssist observations" value={String(metrics.observation_runs ?? 0)} status={metrics.observation_runs ? 'good' : 'neutral'} />
      <MetricCard label="Failures detected" value={String(metrics.total_failures ?? 0)} status={metrics.total_failures ? 'warn' : 'good'} />
      <MetricCard label="Failure rate" value={percent(metrics.failure_rate)} status={qualityStatus(typeof metrics.failure_rate === 'number' ? 1 - metrics.failure_rate : null)} />
      <MetricCard label="Latest workspace quality" value={percent(metrics.overall_quality)} status={qualityStatus(metrics.overall_quality)} />
    </div>

    <div className="grid two">
      <Section title="RAG quality">
        <table><tbody>
          <tr><td>Overall quality</td><td>{percent(metrics.overall_quality)}</td></tr>
          <tr><td>Retrieval match</td><td>{percent(metrics.term_match)}</td></tr>
          <tr><td>Source coverage</td><td>{percent(metrics.source_coverage)}</td></tr>
          <tr><td>Answer relevancy</td><td>{percent(metrics.answer_relevancy)}</td></tr>
          <tr><td>Faithfulness</td><td>{percent(metrics.faithfulness)}</td></tr>
        </tbody></table>
        {!hasWorkspaceQuality && <p className="answer">No labeled RAGGuard workspace evaluation is available yet. TrustAssist observation scores are shown in Query Runs.</p>}
      </Section>
      <Section title="Current index">
        <table><tbody>
          <tr><td>Indexed documents</td><td>{data.index.documents}</td></tr>
          <tr><td>Searchable chunks</td><td>{data.index.chunks}</td></tr>
          <tr><td>Retriever</td><td>{data.embedding.model}</td></tr>
          <tr><td>Vocabulary terms</td><td>{data.embedding.dimension}</td></tr>
          <tr><td>Latest retrieval latency</td><td>{data.embedding.latency_ms == null ? '—' : `${data.embedding.latency_ms} ms`}</td></tr>
        </tbody></table>
      </Section>
    </div>

    <Section title="Recent activity">
      {recentRuns.length ? <div className="operations-table-wrap"><table className="operations-table">
        <thead><tr><th>Time</th><th>Application</th><th>Environment</th><th>Query</th><th>Status</th><th>Method</th><th>Chunks</th></tr></thead>
        <tbody>{recentRuns.map((run: any) => <tr key={run.id}>
          <td>{new Date(run.created_at).toLocaleString()}</td><td>{run.application_id || 'RAGGuard workspace'}</td>
          <td>{run.environment || '—'}</td><td className="activity-query">{run.query}</td><td>{run.status}</td>
          <td>{run.method || 'unknown'}</td><td>{run.retrieved_count ?? '—'}</td>
        </tr>)}</tbody>
      </table></div> : <p className="answer">No recent activity.</p>}
      <p className="activity-refresh-note">Dashboard refreshes every {REFRESH_MS / 1000} seconds.</p>
    </Section>

    <Section title="Recent failures">
      <div className="failure-list">{data.recent_failures?.length ? data.recent_failures.map((failure: any) => <article key={failure.id}>
        <b>{failure.type}</b><span>{failure.application_id ? `${failure.application_id} · ` : ''}{failure.severity} · {failure.query}</span>
      </article>) : <p className="answer">No failures have been recorded yet.</p>}</div>
    </Section>
  </div>
}
