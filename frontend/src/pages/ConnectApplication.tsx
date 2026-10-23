import { useEffect, useMemo, useState } from 'react'
import { getApplications, getIntegrationMethods, onboardApplication, prepareApplicationIntegration, rotateApplicationCredential, type RegisteredApplication } from '../api/client'

type IntegrationMethod = {
  id: string
  label: string
  kind: string
  best_for: string
  technical_level: string
  summary: string
  instructions: string[]
}

type IntegrationPlan = {
  application_name: string
  suggested_application_id: string
  environment: string
  framework: string
  knowledge_source: string
  recommended_method: IntegrationMethod
  checklist: string[]
  security_notes: string[]
  status: string
  next_steps: string[]
  python_example?: string | null
}

const defaultPlan = {
  application_name: '',
  environment: 'development',
  framework: 'python',
  knowledge_source: 'observation_only',
  integration_method: 'python-adapter',
}

export default function ConnectApplication() {
  const [methods, setMethods] = useState<IntegrationMethod[]>([])
  const [methodsLoading, setMethodsLoading] = useState(true)
  const [methodsError, setMethodsError] = useState('')
  const [applications, setApplications] = useState<RegisteredApplication[]>([])
  const [form, setForm] = useState(defaultPlan)
  const [plan, setPlan] = useState<IntegrationPlan | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [copied, setCopied] = useState(false)
  const [connectionNotice, setConnectionNotice] = useState('')
  const [adminCredential, setAdminCredential] = useState('')
  const [provisioning, setProvisioning] = useState(false)
  const [issuedCredential, setIssuedCredential] = useState<{ application: RegisteredApplication; token: string } | null>(null)

  const refreshApplications = async () => {
    setRefreshing(true)
    try {
      const latest = await getApplications()
      setApplications(latest)
      const matching = latest.find((application) =>
        (application.application_id.toLowerCase() === form.application_name.trim().toLowerCase()
          || application.display_name.toLowerCase() === form.application_name.trim().toLowerCase())
        && application.environment === form.environment,
      )
      if (matching?.connection_status === 'connected') {
        const evaluation = matching.last_evaluation_status === 'failure' ? 'The observation was evaluated and a reliability issue was detected.' : 'The observation was evaluated successfully.'
        setConnectionNotice(`Connection test successful: RAGGuard received an observation from ${matching.display_name}. ${evaluation} Repair permission is ${matching.repair_authorized ? 'enabled' : 'disabled'}.`)
      } else if (matching?.connection_status === 'stale') {
        setConnectionNotice(`RAGGuard received an observation from ${matching.display_name}, but the latest one is older than 24 hours. Send a new observation to confirm active monitoring.`)
      } else if (matching) {
        setConnectionNotice(`Application ${matching.display_name} is registered, but RAGGuard has not received an observation yet.`)
      } else {
        setConnectionNotice('No matching application is registered in this workspace yet. A setup plan does not register it.')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not refresh application status.')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    let active = true
    getIntegrationMethods()
      .then((integrationMethods) => { if (active) setMethods(integrationMethods) })
      .catch((reason) => { if (active) setMethodsError(reason instanceof Error ? reason.message : 'Could not load integration methods.') })
      .finally(() => { if (active) setMethodsLoading(false) })
    getApplications()
      .then((allApplications) => {
        if (!active) return
        setApplications(allApplications)
        const selected = allApplications.find((item) => item.application_id.toLowerCase() === form.application_name.toLowerCase())
        if (selected) setForm((current) => ({ ...current, environment: selected.environment || current.environment }))
      })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load registered applications.') })
    return () => { active = false }
  }, [])

  const currentMethod = useMemo(() => methods.find((method) => method.id === form.integration_method) ?? methods[0], [form.integration_method, methods])

  const generatePlan = async () => {
    if (!form.application_name.trim()) {
      setError('Application name is required.')
      return
    }
    setBusy(true)
    setError('')
    setIssuedCredential(null)
    setConnectionNotice('')
    try {
      const result = await prepareApplicationIntegration({
        application_name: form.application_name.trim(),
        framework: form.framework,
        environment: form.environment,
        knowledge_source: form.knowledge_source,
        integration_method: form.integration_method,
      })
      setPlan(result)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The integration plan could not be prepared.')
    } finally {
      setBusy(false)
    }
  }

  const registerApplication = async () => {
    if (!plan) return
    if (plan.knowledge_source !== 'observation_only') {
      setError('This guided registration flow currently provisions observation-only monitoring. Managed-index and external-query registrations need their additional configuration first.')
      return
    }
    if (!adminCredential) {
      setError('Enter the workspace administrator credential to register this application.')
      return
    }
    setProvisioning(true)
    setError('')
    try {
      const result = await onboardApplication({
        application_id: plan.suggested_application_id,
        display_name: plan.application_name,
        environment: plan.environment,
      }, adminCredential)
      const { observation_credential: token, ...application } = result
      setIssuedCredential({ application, token })
      setAdminCredential('')
      setApplications(await getApplications())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not register this application.')
    } finally {
      setProvisioning(false)
    }
  }

  const rotateCredential = async (application: RegisteredApplication) => {
    if (!adminCredential) {
      setError('Enter the workspace administrator credential above before rotating a credential.')
      return
    }
    setProvisioning(true)
    setError('')
    try {
      const result = await rotateApplicationCredential(application, adminCredential)
      const { observation_credential: token, ...updatedApplication } = result
      setIssuedCredential({ application: updatedApplication, token })
      setAdminCredential('')
      setApplications(await getApplications())
      setConnectionNotice('A replacement credential was issued. Update your app host secret; the old credential has been invalidated.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not rotate this credential.')
    } finally {
      setProvisioning(false)
    }
  }

  const recommendedSummary = currentMethod ? currentMethod.summary : 'Use the recommended connection method for your application type.'

  return <div className="page">
    <div className="narrator">
      <div className="narrator-mark">ONB</div>
      <div>
        <div className="eyebrow">GUIDED INTEGRATION</div>
        <h3>Set up monitoring for your RAG application</h3>
        <p>Choose a setup method and follow its instructions. RAGGuard only marks an application connected after it receives and evaluates an observation. Monitoring never grants repair permission.</p>
      </div>
    </div>

    <div className="grid two">
      <section className="section card">
        <div className="section-head"><h2>Application details</h2></div>
        <div className="connect-form">
          <label>
            <span>Application name</span>
            <input value={form.application_name} placeholder="e.g. my-rag-app" onChange={(event) => setForm((current) => ({ ...current, application_name: event.target.value }))} />
          </label>
          <label>
            <span>Environment</span>
            <select value={form.environment} onChange={(event) => setForm((current) => ({ ...current, environment: event.target.value }))}>
              <option value="development">Development</option>
              <option value="staging">Staging</option>
              <option value="production">Production</option>
            </select>
          </label>
          <label>
            <span>Application type</span>
            <select value={form.framework} onChange={(event) => setForm((current) => ({ ...current, framework: event.target.value }))}>
              <option value="python">Python RAG application</option>
              <option value="langchain">LangChain / LangGraph</option>
              <option value="llamaindex">LlamaIndex</option>
              <option value="custom">Custom application</option>
            </select>
          </label>
          <label>
            <span>Integration method</span>
            <select value={form.integration_method} onChange={(event) => setForm((current) => ({ ...current, integration_method: event.target.value }))}>
              {methods.map((method) => <option key={method.id} value={method.id}>{method.label}</option>)}
            </select>
          </label>
          <label>
            <span>Knowledge source</span>
            <select value={form.knowledge_source} onChange={(event) => setForm((current) => ({ ...current, knowledge_source: event.target.value }))}>
              <option value="observation_only">Monitor my existing RAG app (keep my index)</option>
              <option value="external_rag_api">Let RAGGuard query my external RAG API</option>
              <option value="managed_index">Use a RAGGuard-managed index</option>
            </select>
            <small>Monitoring your existing app does not require moving documents or changing its index.</small>
          </label>
          <button className="primary connect-button" onClick={() => void generatePlan()} disabled={busy}>{busy ? 'Preparing…' : 'Generate setup plan'}</button>
          {error && <p className="activity-error" role="alert">{error}</p>}
        </div>
      </section>

      <section className="section card">
        <div className="section-head"><h2>Recommended connection method</h2></div>
        <div className="connect-summary">
          {currentMethod ? (
            <>
              <div className="pill-row"><span className="tag">{currentMethod.kind}</span><span className="tag">{currentMethod.technical_level}</span></div>
              <h3>{currentMethod.label}</h3>
              <p>{recommendedSummary}</p>
              <ul>
                <li><strong>Best for:</strong> {currentMethod.best_for}</li>
                <li><strong>Setup:</strong> {currentMethod.instructions[0]}</li>
              </ul>
            </>
          ) : methodsLoading ? <p>Loading available integration methods…</p>
            : <p className="activity-error" role="alert">{methodsError || 'No integration methods are available.'}</p>}
        </div>
      </section>
    </div>

    {plan && <section className="section card connect-results">
      <div className="section-head"><h2>Setup instructions</h2><span className="tag">Setup plan created</span></div>
      <div className="connect-plan-grid">
        <div>
          <h3>{plan.application_name} · {plan.environment}</h3>
          <p className="answer">The recommended method is <strong>{plan.recommended_method.label}</strong>. This page created a setup plan. Application registration is {applications.some((application) => application.application_id.toLowerCase() === plan.suggested_application_id.toLowerCase() && application.environment === plan.environment) ? 'complete' : 'not complete'}; the one-time credential is {issuedCredential?.application.application_id === plan.suggested_application_id ? 'available below' : 'hidden until you issue or rotate it'}.</p>
          <ol className="checklist">
            <li>Setup plan created: complete.</li>
            <li>Application registered: {applications.some((application) => application.application_id.toLowerCase() === plan.suggested_application_id.toLowerCase() && application.environment === plan.environment) ? 'yes' : 'not yet'}.</li>
            <li>Connected: {applications.some((application) => application.application_id.toLowerCase() === plan.suggested_application_id.toLowerCase() && application.environment === plan.environment && application.connection_status === 'connected') ? 'yes, a recent observation was evaluated' : 'not yet verified'}.</li>
          </ol>
          <ol>
            {plan.next_steps.map((step) => <li key={step}>{step}</li>)}
          </ol>
          {plan.python_example && <details className="connect-code">
            <summary>Developer instructions (optional)</summary>
            <p className="answer">The Python observer is included in the RAGGuard source package, which is not currently published as a standalone installable package. Add it after your app retrieves documents. RAGGuard cannot identify the exact source file in your application from this workspace.</p>
            <div className="section-head"><h3>Python example</h3><button className="ghost" onClick={() => { void navigator.clipboard.writeText(plan.python_example || '').then(() => setCopied(true)) }}>{copied ? 'Copied' : 'Copy example'}</button></div>
            <pre><code>{plan.python_example}</code></pre>
          </details>}
          <section className="onboard-action">
            <h3>Register this application</h3>
            <p className="answer">A workspace administrator must authorize registration. The administrator credential is sent securely for this request and is not saved in this page.</p>
            <p className="answer">This guided registration provisions observation-only monitoring. It does not change your retrieval system or grant RAGGuard access to your index.</p>
            <label>
              <span>Workspace administrator credential</span>
              <input type="password" autoComplete="current-password" value={adminCredential} onChange={(event) => setAdminCredential(event.target.value)} />
            </label>
            <button className="primary" onClick={() => void registerApplication()} disabled={provisioning || !adminCredential || plan.knowledge_source !== 'observation_only'}>{provisioning ? 'Registering…' : 'Register and create observation credential'}</button>
          </section>
          {issuedCredential && <section className="credential-once" role="status">
            <h3>Application registered · credential shown once</h3>
            <p>Save this value in your app host's secret settings as <code>RAGGUARD_OBSERVATION_TOKEN</code>. RAGGuard stores only a hash, so this value cannot be shown again. Do not commit it to source control.</p>
            <div className="credential-value"><code>{issuedCredential.token}</code><button className="ghost" onClick={() => { void navigator.clipboard.writeText(issuedCredential.token).then(() => setCopied(true)) }}>{copied ? 'Copied' : 'Copy credential'}</button></div>
            <p>Application ID: <code>{issuedCredential.application.application_id}</code> · Environment: <code>{issuedCredential.application.environment}</code>. Repair authorization is disabled.</p>
          </section>}
        </div>
        <div>
          <h3>What still needs to happen</h3>
          <ul className="checklist">
            {plan.checklist.map((item) => <li key={item}>{item}</li>)}
          </ul>
          <p className="answer"><strong>Registration and credential:</strong> ask your RAGGuard workspace administrator to register the suggested application ID and create its observation credential. Put that credential in your app deployment's secret settings as <code>RAGGUARD_OBSERVATION_TOKEN</code>; do not paste it here or commit it to source control. This page cannot generate or display credentials yet. Repair permission stays off unless explicitly granted.</p>
          <h3>Security</h3>
          <ul className="checklist">
            {plan.security_notes.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </div>
    </section>}

    <section className="section card">
      <div className="section-head"><h2>Application connection status</h2><button className="ghost" onClick={() => void refreshApplications()} disabled={refreshing}>{refreshing ? 'Checking…' : 'Check connection'}</button></div>
      <p className="answer">Registered means RAGGuard knows the application. Connected means it received an observation in the last 24 hours. Older observations are shown as stale. A connection check does not run repairs.</p>
      {connectionNotice && <p className="answer" role="status">{connectionNotice}</p>}
      {applications.length > 0 ? <div className="registration-grid">
        {applications.map((application) => (
          <div key={`${application.application_id}:${application.environment}`} className="registration-card">
            <strong>{application.application_id}</strong>
            <span>{application.environment}</span>
            <small>{application.connection_status === 'connected' ? 'Connected · recent observation received' : application.connection_status === 'stale' ? 'Registered · last observation is older than 24 hours' : 'Registered · waiting for first observation'}</small>
            {application.last_observed_at && <small>Last observation: {new Date(application.last_observed_at).toLocaleString()}</small>}
            <small>{application.repair_authorized ? 'Repair permission is enabled' : 'Repair permission is off'}</small>
            {plan && <button className="ghost" onClick={() => void rotateCredential(application)} disabled={provisioning}>Rotate observation credential</button>}
          </div>
        ))}
      </div> : <p className="answer">No registered applications are visible in this workspace. Application registration requires an administrator.</p>}
    </section>
  </div>
}
