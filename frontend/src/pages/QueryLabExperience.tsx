import { useEffect, useState } from 'react'
import { getApplications, getDashboard, runQuery, runRepair, type RegisteredApplication } from '../api/client'
import { MetricCard, Section } from '../components/Cards'
import '../styles/query-lab.css'

const refreshScope = getDashboard
const percent = (value: unknown) => typeof value === 'number' ? `${Math.round(value * 100)}%` : '--'
const score = (value: unknown) => typeof value === 'number' ? value.toFixed(3) : '--'

type Source = {
  chunk_id: string
  document_id: string
  source: string
  section?: string | null
  text: string
  score: number
}

type QueryResult = {
  answer: string
  rag_status: string
  retrieval_method: string
  latency_ms: number
  retrieval_quality: Record<string, number>
  reliability_evaluation: {
    retrieved_count: number
    top_score: number | null
    score_margin: number | null
    duplicate_ratio: number
    signals: Record<string, boolean>
    status: 'HEALTHY' | 'DEGRADED' | 'FAILURE'
  }
  reliability_failure: {
    failure_type: string
    severity: string
    evidence: string[]
  } | null
  sources: Source[]
}

type Scope = {
  ragguard_tenant_id: string
}

type RepairCheck = {
  response: any
  before: QueryResult
  after: QueryResult | null
}

function Check({ label, detail, passed }: { label: string; detail: string; passed: boolean }) {
  return <div className={`query-check ${passed ? 'passed' : 'failed'}`}>
    <span aria-hidden="true">{passed ? '✓' : '!'}</span>
    <div><strong>{label}</strong><small>{detail}</small></div>
  </div>
}

function recommendation(failureType: string) {
  if (failureType === 'NO_RETRIEVAL') return 'Do not treat a generated answer as grounded; inspect the selected index and its source coverage.'
  if (failureType === 'DUPLICATE_CONTEXT') return 'Review duplicate chunks in the selected index before relying on this retrieval.'
  if (failureType === 'WEAK_RETRIEVAL') return 'Inspect the retrieved passages and scores; the top score is below the live reliability threshold.'
  if (failureType === 'EMBEDDING_DEGRADED') return 'Inspect the configured embedding or fallback path before relying on this retrieval.'
  return 'Review the retrieved context and detector evidence before relying on this result.'
}

function repairStatus(status: string) {
  return status.replace(/_/g, ' ')
}

export default function QueryLabExperience() {
  const [query, setQuery] = useState('')
  const [method, setMethod] = useState('hybrid')
  const [topK, setTopK] = useState(5)
  const [applications, setApplications] = useState<RegisteredApplication[]>([])
  const [applicationId, setApplicationId] = useState('')
  const [environment, setEnvironment] = useState('')
  const [scope, setScope] = useState<Scope | null>(null)
  const [scopeLoaded, setScopeLoaded] = useState(false)
  const [scopeError, setScopeError] = useState('')
  const [applicationError, setApplicationError] = useState('')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [selectedRelevant, setSelectedRelevant] = useState<string[]>([])
  const [manualRelevantIds, setManualRelevantIds] = useState('')
  const [repairCheck, setRepairCheck] = useState<RepairCheck | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [repairBusy, setRepairBusy] = useState(false)

  useEffect(() => {
    let active = true
    Promise.allSettled([refreshScope(), getApplications()])
      .then(([dashboardResult, applicationsResult]) => {
        if (!active) return
        const dashboard = dashboardResult.status === 'fulfilled' ? dashboardResult.value : null
        if (dashboard?.scope?.ragguard_tenant_id) {
          setScope({ ragguard_tenant_id: dashboard.scope.ragguard_tenant_id })
        } else if (dashboardResult.status === 'rejected') {
          setScopeError(dashboardResult.reason instanceof Error ? dashboardResult.reason.message : 'Dashboard scope unavailable')
        }
        if (applicationsResult.status === 'fulfilled') {
          const registeredApplications = applicationsResult.value
          setApplications(registeredApplications)
          const initial = registeredApplications.find((item) => (
            item.queryable
            && item.application_id === dashboard?.scope?.application_id
            && item.environment === dashboard?.scope?.environment
          )) || registeredApplications.find((item) => item.queryable)
          if (initial) {
            setApplicationId(initial.application_id)
            setEnvironment(initial.environment)
          } else if (registeredApplications.length) {
            setApplicationError('Registered applications are available, but none can be queried from Query Lab.')
          }
        } else {
          setApplicationError(applicationsResult.reason instanceof Error ? applicationsResult.reason.message : 'Application registry unavailable')
        }
      })
      .finally(() => { if (active) setScopeLoaded(true) })
    return () => { active = false }
  }, [])

  const runTest = async () => {
    if (!query.trim()) return
    setBusy(true)
    setError('')
    setRepairCheck(null)
    setSelectedRelevant([])
    try {
      setResult(await runQuery(query.trim(), topK, method, false, applicationId, environment))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Query test failed')
    } finally {
      setBusy(false)
    }
  }

  const toggleRelevant = (chunkId: string) => {
    setSelectedRelevant((current) => current.includes(chunkId)
      ? current.filter((item) => item !== chunkId)
      : [...current, chunkId])
  }

  const relevantChunkIds = [...new Set([
    ...selectedRelevant,
    ...manualRelevantIds.split(/[\s,]+/).filter(Boolean),
  ])]

  const runRecoveryTest = async () => {
    if (!result || !query.trim() || relevantChunkIds.length === 0) return
    setRepairBusy(true)
    setError('')
    const before = result
    try {
      const response = await runRepair(query.trim(), before.answer, relevantChunkIds, topK, applicationId, environment)
      setRepairCheck({ response, before, after: null })
      try {
        const after = await runQuery(query.trim(), topK, method, false, applicationId, environment)
        setResult(after)
        setRepairCheck({ response, before, after })
        setSelectedRelevant([])
      } catch (reason) {
        setError(`Repair completed, but the comparison query failed: ${reason instanceof Error ? reason.message : 'query unavailable'}`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Repair test failed')
    } finally {
      setRepairBusy(false)
    }
  }

  const evaluation = result?.reliability_evaluation
  const failure = result?.reliability_failure
  const signals = evaluation?.signals || {}
  const quality = result?.retrieval_quality || {}
  const selectedApplication = applications.find((application) => (
    application.application_id === applicationId
    && application.environment === environment
  ))
  const applicationChoices = [...new Map(applications.map((application) => [
    application.application_id,
    application,
  ])).values()]
  const environmentChoices = applications.filter((application) => (
    application.application_id === applicationId
  ))
  const canAttemptRepair = Boolean(
    failure
    && selectedApplication?.knowledge_source === 'managed_index'
    && relevantChunkIds.length
    && !repairBusy,
  )

  return <div className="page query-lab-page">
    <div className="recoveries-heading">
      <div><span className="recovery-eyebrow">CONTROLLED TESTING</span><h2>Query Lab</h2></div>
    </div>
    <Section title="Test target">
      <div className="query-target-grid">
        <label>Application
          <select value={applicationId} disabled={!applications.length} onChange={(event) => {
            const next = applications.find((application) => application.application_id === event.target.value)
            setApplicationId(event.target.value)
            setEnvironment(next?.environment || '')
            setResult(null)
            setRepairCheck(null)
          }}>
            {!applications.length && <option value="">{!scopeLoaded ? 'Loading applications…' : applicationError ? 'Application registry unavailable' : 'No registered applications'}</option>}
            {applicationChoices.map((application) => <option key={application.application_id} value={application.application_id}>{application.display_name}</option>)}
          </select>
        </label>
        <label>Environment
          <select value={environment} disabled={!environmentChoices.length} onChange={(event) => {
            setEnvironment(event.target.value)
            setResult(null)
            setRepairCheck(null)
          }}>
            {environmentChoices.map((application) => <option key={application.environment} value={application.environment}>{application.environment}</option>)}
          </select>
        </label>
        <div className="query-target-index"><span>Knowledge source</span><strong>{selectedApplication?.knowledge_source.replace(/_/g, ' ') || 'Unavailable'}</strong></div>
      </div>
      <p className="operations-note">Application choices are registered to the current RAGGuard tenant. Query tests do not create production Query Runs; observation-only applications remain visible but cannot be queried here.</p>
      {scopeError && <div className="recovery-error" role="alert">Could not load dashboard scope (/dashboard): {scopeError}</div>}
      {applicationError && <div className="recovery-error" role="alert">Could not load queryable applications: {applicationError}</div>}
      {scope && <small className="query-scope-id">RAGGuard tenant: {scope.ragguard_tenant_id}</small>}
    </Section>

    <Section title="Run a controlled query">
      <label className="query-prompt-label" htmlFor="query-lab-prompt">Query</label>
      <textarea
        id="query-lab-prompt"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') void runTest()
        }}
        placeholder={`Ask a question against ${selectedApplication?.display_name || 'the selected application'}`}
      />
      <div className="controls query-lab-controls">
        <label>Retrieval method<select value={method} onChange={(event) => setMethod(event.target.value)}>
          <option value="hybrid">Hybrid</option><option value="vector">Vector</option><option value="keyword">Keyword</option>
        </select></label>
        <label>Top K<select value={topK} onChange={(event) => setTopK(Number(event.target.value))}>
          <option value={3}>3</option><option value={5}>5</option><option value={10}>10</option>
        </select></label>
        <button className="primary" onClick={() => void runTest()} disabled={busy || !query.trim() || !selectedApplication?.queryable}>
          {busy ? 'Running test…' : 'Run test'}
        </button>
      </div>
      {error && <div className="recovery-error" role="alert">{error}</div>}
    </Section>

    {result && evaluation && <>
      <div className="query-lab-result-heading">
        <div><span className="recovery-eyebrow">RETRIEVAL → EVALUATION → DETECTION</span><h2>Test result</h2></div>
        <span className={`recovery-pill ${evaluation.status === 'HEALTHY' ? 'promoted' : evaluation.status === 'FAILURE' ? 'escalated' : 'rolled_back'}`}>
          {evaluation.status}
        </span>
      </div>

      <Section title="Retrieval inspection">
        <div className="metrics compact query-lab-metrics">
          <MetricCard label="Chunks retrieved" value={String(evaluation.retrieved_count)} status={evaluation.retrieved_count ? 'good' : 'bad'} />
          <MetricCard label="Top score" value={score(evaluation.top_score)} status={signals.weak_retrieval ? 'warn' : 'good'} />
          <MetricCard label="Score margin" value={score(evaluation.score_margin)} />
          <MetricCard label="Duplicate ratio" value={percent(evaluation.duplicate_ratio)} status={signals.duplicate_context ? 'warn' : 'good'} />
          <MetricCard label="Retrieval latency" value={`${Math.round(result.latency_ms)} ms`} />
        </div>
        <div className="query-check-list">
          <Check label="Retrieval availability" detail={`${evaluation.retrieved_count} chunks returned by ${result.retrieval_method}.`} passed={!signals.no_retrieval} />
          <Check
            label="Retrieval strength"
            detail={evaluation.top_score === null ? 'No top score is available because retrieval returned no chunks.' : signals.weak_retrieval ? 'Top score is below the detector threshold.' : 'Top score met the detector threshold.'}
            passed={evaluation.top_score !== null && !signals.weak_retrieval}
          />
          <Check label="Duplicate context" detail={signals.duplicate_context ? `${percent(evaluation.duplicate_ratio)} of retrieved IDs are duplicates.` : `${percent(evaluation.duplicate_ratio)} duplicate ratio.`} passed={!signals.duplicate_context} />
          <div className="query-check query-neutral"><span aria-hidden="true">i</span><div><strong>Embedding fallback</strong><small>Not applicable to this local TF-IDF managed index.</small></div></div>
        </div>
        {failure && <div className="query-failure-callout">
          <div><span className="recovery-eyebrow">{failure.severity.toUpperCase()} SEVERITY</span><h3>{failure.failure_type}</h3></div>
          <p>{failure.evidence.join(' ')}</p>
          <strong>Recommendation</strong><p>{recommendation(failure.failure_type)}</p>
        </div>}
      </Section>

      <div className="grid two">
        <Section title="Answer">
          <p className="answer">{result.answer}</p>
          <span className={`recovery-pill ${result.rag_status === 'grounded' ? 'promoted' : 'escalated'}`}>{result.rag_status}</span>
        </Section>
        <Section title="Heuristic answer checks">
          <p className="operations-note">These are local text-overlap estimates, not labeled evaluation or a reliability certificate.</p>
          <table><tbody>
            <tr><td>Answer relevance estimate</td><td>{percent(quality.answer_relevancy)}</td></tr>
            <tr><td>Context support estimate</td><td>{percent(quality.faithfulness)}</td></tr>
            <tr><td>Term match proxy</td><td>{percent(quality.term_match)}</td></tr>
            <tr><td>Source coverage</td><td>{percent(quality.source_coverage)}</td></tr>
          </tbody></table>
        </Section>
      </div>

      <Section title={`Retrieved chunks · ${result.sources.length}`}>
        {result.sources.length ? <>
          <p className="operations-note">Scores are managed-index retrieval scores. Select only chunks that you independently know are relevant to use them as ground truth for a repair test.</p>
          <div className="context">{result.sources.map((source) => <article className="query-source" key={source.chunk_id}>
            {selectedApplication?.knowledge_source === 'managed_index' && <label className="query-source-select">
              <input type="checkbox" checked={selectedRelevant.includes(source.chunk_id)} onChange={() => toggleRelevant(source.chunk_id)} />
              <span>Ground-truth relevant</span>
            </label>}
            <b>{source.section || source.source}</b>
            <span>{source.source} · score {source.score.toFixed(3)}</span>
            <p>{source.text}</p>
          </article>)}</div>
        </> : <p className="operations-empty">No chunks were retrieved. Inspect the active index; a repair test requires at least one independently labeled relevant chunk.</p>}
      </Section>

      {failure && selectedApplication?.knowledge_source === 'managed_index' && <Section title="Recovery test">
        <p className="operations-note">Recovery is opt-in and requires ground-truth evidence. Select known-relevant retrieved chunks above, or enter chunk IDs independently labeled as relevant (comma or newline separated).</p>
        <label className="query-prompt-label" htmlFor="query-lab-relevant-ids">Ground-truth chunk IDs</label>
        <textarea
          id="query-lab-relevant-ids"
          className="query-relevant-ids"
          value={manualRelevantIds}
          onChange={(event) => setManualRelevantIds(event.target.value)}
          placeholder="policy-chunk-12, policy-chunk-18"
        />
        <div className="query-repair-action">
          <div><strong>{relevantChunkIds.length} ground-truth chunk{relevantChunkIds.length === 1 ? '' : 's'} selected</strong><small>Repair runs against the managed index, validates the result, and records it in workspace repair history.</small></div>
          <button className="primary" onClick={() => void runRecoveryTest()} disabled={!canAttemptRepair}>
            {repairBusy ? 'Repairing and rechecking…' : 'Run repair test'}
          </button>
        </div>
      </Section>}

      {repairCheck && <Section title="Repair comparison">
        <p className="operations-note">Repair path: RAGGuard managed vector index · outcome: {repairStatus(repairCheck.response.status)}</p>
        <div className="grid two">
          <div className="query-comparison"><strong>Before</strong><span>{repairCheck.before.reliability_evaluation.retrieved_count} chunks · top score {score(repairCheck.before.reliability_evaluation.top_score)} · {repairCheck.before.reliability_evaluation.status}</span></div>
          <div className="query-comparison"><strong>After</strong><span>{repairCheck.after ? `${repairCheck.after.reliability_evaluation.retrieved_count} chunks · top score ${score(repairCheck.after.reliability_evaluation.top_score)} · ${repairCheck.after.reliability_evaluation.status}` : 'Repair completed; comparison query unavailable.'}</span></div>
        </div>
        <p>Validation: {repairCheck.response.validated == null ? 'not reported' : repairCheck.response.validated ? 'passed' : 'failed'} · Score change: {score(repairCheck.response.improvement)}</p>
        <p>Strategies: {repairCheck.response.attempted_repairs?.length ? repairCheck.response.attempted_repairs.join(', ') : 'none'}</p>
      </Section>}
    </>}
  </div>
}
