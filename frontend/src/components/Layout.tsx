import { useEffect, useState, type ReactNode } from 'react'
import { getApiHealth, getApplications, getApplicationScope, getDefaultDashboard, setApplicationScope, type RegisteredApplication } from '../api/client'

const items = [
  ['overview', 'Overview'],
  ['connect', 'Connect Application'],
  ['query', 'Query Lab'],
  ['runs', 'Query Runs'],
  ['recoveries', 'Recoveries'],
  ['failures', 'Failures'],
  ['escalations', 'Escalations'],
  ['strategies', 'Repair Analytics'],
  ['applications', 'Applications'],
  ['audit', 'Audit Explorer'],
  ['capabilities', 'Repair Capabilities'],
  ['documents', 'Documents'],
]

const icons: Record<string, string> = {
  overview: '◈', connect: '＋', query: '⌕', runs: '◉', recoveries: '↻', failures: '!',
  escalations: '↗', strategies: '⇄', applications: '▦', audit: '≡',
  capabilities: '⚙', documents: '▤',
}

export default function Layout({ page, setPage, children }: {
  page: string
  setPage: (page: string) => void
  children: ReactNode
}) {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null)
  const [scope, setScope] = useState<{ ragguard_tenant_id: string; application_id: string; environment: string } | null>(null)
  const [applications, setApplications] = useState<RegisteredApplication[]>([])
  useEffect(() => {
    let active = true
    const check = () => getApiHealth().then(() => { if (active) setApiOnline(true) }).catch(() => { if (active) setApiOnline(false) })
    check()
    void Promise.all([getDefaultDashboard(), getApplications()]).then(([dashboard, items]) => {
      if (!active) return
      setApplications(items)
      const saved = getApplicationScope()
      const selected = saved && items.find((item) => item.application_id === saved.application_id && item.environment === saved.environment)
      const current = dashboard.scope && items.find((item) => item.application_id === dashboard.scope.application_id && item.environment === dashboard.scope.environment)
      const fallback = selected || current || items[0]
      if (fallback) {
        setApplicationScope({ application_id: fallback.application_id, environment: fallback.environment })
        setScope({ ragguard_tenant_id: fallback.ragguard_tenant_id || dashboard.scope?.ragguard_tenant_id || '', application_id: fallback.application_id, environment: fallback.environment })
      } else setScope(dashboard.scope || null)
    }).catch(() => { if (active) setApplications([]) })
    const timer = window.setInterval(check, 30000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  function changeApplicationScope(value: string) {
    const [application_id, environment] = value.split('::')
    if (!application_id || !environment) return
    setApplicationScope({ application_id, environment })
    window.location.reload()
  }

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><span className="brand-dot">RG</span><div><strong>RAGGuard</strong><small>Reliability Control Center</small></div></div>
      <nav>{items.map(([id, label]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}>
        <span className="nav-icon">{icons[id]}</span>{label}
      </button>)}</nav>
      <div className="side-foot"><span className={`pulse ${apiOnline === false ? 'offline' : ''}`} /> API {apiOnline === null ? 'checking' : apiOnline ? 'online' : 'offline'}</div>
    </aside>
    <main className="main">
      <header className="topbar">
        <div><span className="crumb">RAGGUARD / {page.toUpperCase()}</span><h1>AI Reliability Control Center</h1></div>
        <div className="top-actions">{applications.length > 0 && <label className="scope-picker" aria-label="Application scope"><span>Application</span><select value={scope ? `${scope.application_id}::${scope.environment}` : ''} onChange={(event) => changeApplicationScope(event.target.value)}>{applications.map((application) => <option key={`${application.application_id}::${application.environment}`} value={`${application.application_id}::${application.environment}`}>{application.display_name} · {application.environment}</option>)}</select></label>}<span className="env">{scope ? `${scope.ragguard_tenant_id} · ${scope.application_id} · ${scope.environment}` : 'Scope unavailable'}</span><span className={`healthy ${apiOnline === false ? 'offline' : ''}`}><i /> API {apiOnline === null ? 'checking' : apiOnline ? 'online' : 'offline'}</span></div>
      </header>
      {children}
    </main>
  </div>
}
