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
  const observationRuns = Number(metrics.observation_runs) || 0
  const observationFailures = Number(metrics.observation_failures) || 0
  const healthyObservations = Math.max(0, observationRuns - observationFailures)
  const observationFailureRate = observationRuns
    ? observationFailures / observationRuns
    : null
  const observedApplication = data.scope?.application_id || 'selected application'
  const workspaceRuns = Math.max(0, (Number(metrics.total_runs) || 0) - observationRuns)
  const observedRuns = recentRuns.filter((run: any) => (
    run.source === 'observation'
    && run.tenant_id === data.scope?.ragguard_tenant_id
    && run.application_id === data.scope?.application_id
    && run.environment === data.scope?.environment
  ))
  const workspaceActivity = recentRuns.filter((run: any) => (
    run.source !== 'observation' && run.application_id !== data.scope?.application_id
  ))
  const observedFailures = (data.recent_failures || []).filter((failure: any) => (
    failure.tenant_id === data.scope?.ragguard_tenant_id
    && failure.application_id === data.scope?.application_id
    && failure.environment === data.scope?.environment
  ))
  const workspaceFailures = (data.recent_failures || []).filter((failure: any) => !failure.application_id)

  return <div className="page">
    <NarratorPanel page="Overview" data={{ ...metrics, scope: data.scope }} />
    {error && <p className="activity-error" role="status">Refresh failed: {error}. Showing the last successful update.</p>}
    <div className="metrics">
      <MetricCard label="Workspace queries" value={String(workspaceRuns)} status={workspaceRuns ? 'good' : 'neutral'} />
      <MetricCard label={`${observedApplication} observations`} value={String(observationRuns)} status={observationRuns ? 'good' : 'neutral'} />
      <MetricCard label={`${observedApplication} healthy`} value={String(healthyObservations)} status={healthyObservations ? 'good' : 'neutral'} />
      <MetricCard
        label="Observed reliability events"
        value={observationRuns ? `${observationFailures} / ${observationRuns} (${percent(observationFailureRate)})` : '0 / 0'}
        status={observationFailures ? 'warn' : 'good'}
      />
      <MetricCard label="Latest workspace quality" value={percent(metrics.overall_quality)} status={qualityStatus(metrics.overall_quality)} />
    </div>
    <p className="operations-note">Events are detector-defined retrieval or reliability conditions, not proof that an answer was incorrect. This snapshot covers the {observationRuns} stored observations for <strong>{data.scope?.ragguard_tenant_id || 'unknown tenant'}</strong> / <strong>{observedApplication}</strong>, not a long-term reliability baseline.</p>

    <div className="grid two">
      <Section title="RAGGuard workspace quality">
        <table><tbody>
          <tr><td>Overall quality</td><td>{percent(metrics.overall_quality)}</td></tr>
          <tr><td>Retrieval match</td><td>{percent(metrics.term_match)}</td></tr>
          <tr><td>Source coverage</td><td>{percent(metrics.source_coverage)}</td></tr>
          <tr><td>Answer relevancy</td><td>{percent(metrics.answer_relevancy)}</td></tr>
          <tr><td>Faithfulness</td><td>{percent(metrics.faithfulness)}</td></tr>
        </tbody></table>
        {!hasWorkspaceQuality && <p className="answer">No labeled workspace evaluation is available yet. Application observations are tracked separately above and in Query Runs.</p>}
      </Section>
      <Section title="Current index">
        <table><tbody>
          <tr><td>Indexed documents</td><td>{data.index.documents}</td></tr>
          <tr><td>Searchable chunks</td><td>{data.index.chunks}</td></tr>
          <tr><td>Retriever</td><td>{data.embedding.model}</td></tr>
          <tr><td>Shared embedding vocabulary terms</td><td>{data.embedding.dimension}</td></tr>
          <tr><td>Latest retrieval latency</td><td>{data.embedding.latency_ms == null ? '—' : `${data.embedding.latency_ms} ms`}</td></tr>
        </tbody></table>
      </Section>
    </div>

    <Section title={`${observedApplication} · ${data.scope?.environment || 'unknown environment'} live telemetry`}>
      {observedRuns.length ? <div className="operations-table-wrap"><table className="operations-table">
        <thead><tr><th>Time</th><th>Application</th><th>Environment</th><th>Query</th><th>Status</th><th>Method</th><th>Chunks</th></tr></thead>
        <tbody>{observedRuns.map((run: any) => <tr key={run.id}>
          <td>{new Date(run.created_at).toLocaleString()}</td><td>{run.application_id || 'RAGGuard workspace'}</td>
          <td>{run.environment || '—'}</td><td className="activity-query">{run.query}</td><td>{run.status}</td>
          <td>{run.method || 'unknown'}</td><td>{run.retrieved_count ?? '—'}</td>
        </tr>)}</tbody>
      </table></div> : <p className="answer">No recent observations were returned for this RAGGuard tenant, application, and environment.</p>}
      <p className="activity-refresh-note">Dashboard refreshes every {REFRESH_MS / 1000} seconds.</p>
    </Section>

    <Section title={`${observedApplication} · ${data.scope?.environment || 'unknown environment'} reliability events`}>
      <div className="failure-list">{observedFailures.length ? observedFailures.map((failure: any) => <article key={failure.id}>
        <b>{failure.type}</b><span>{failure.application_id ? `${failure.application_id} · ` : ''}{failure.severity} · {failure.query}</span>
      </article>) : <p className="answer">No observed application failures.</p>}</div>
    </Section>

    <Section title="RAGGuard workspace activity">
      {workspaceActivity.length ? <div className="operations-table-wrap"><table className="operations-table">
        <thead><tr><th>Time</th><th>Query</th><th>Status</th><th>Method</th><th>Latency</th></tr></thead>
        <tbody>{workspaceActivity.map((run: any) => <tr key={run.id}>
          <td>{new Date(run.created_at).toLocaleString()}</td><td className="activity-query">{run.query}</td>
          <td>{run.status}</td><td>{run.method || 'unknown'}</td>
          <td>{typeof run.latency_ms === 'number' ? `${Math.round(run.latency_ms)} ms` : '—'}</td>
        </tr>)}</tbody>
      </table></div> : <p className="answer">No recent workspace queries.</p>}
    </Section>

    <Section title="RAGGuard workspace failures">
      <div className="failure-list">{workspaceFailures.length ? workspaceFailures.map((failure: any) => <article key={failure.id}>
        <b>{failure.type}</b><span>{failure.severity} · {failure.query}</span>
      </article>) : <p className="answer">No recent workspace failures.</p>}</div>
    </Section>
  </div>
}
