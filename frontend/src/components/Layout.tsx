import { useEffect, useState, type ReactNode } from 'react'
import { getApiHealth, getDashboard } from '../api/client'

const items = [
  ['overview', 'Overview'],
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
  overview: '◈', query: '⌕', runs: '◉', recoveries: '↻', failures: '!',
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
  useEffect(() => {
    let active = true
    const check = () => getApiHealth().then(() => { if (active) setApiOnline(true) }).catch(() => { if (active) setApiOnline(false) })
    const loadScope = () => getDashboard().then((dashboard) => { if (active) setScope(dashboard.scope || null) }).catch(() => { if (active) setScope(null) })
    check()
    void loadScope()
    const timer = window.setInterval(check, 30000)
    const scopeTimer = window.setInterval(loadScope, 30000)
    return () => { active = false; window.clearInterval(timer); window.clearInterval(scopeTimer) }
  }, [])

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
        <div className="top-actions"><span className="env">{scope ? `${scope.ragguard_tenant_id} · ${scope.application_id} · ${scope.environment}` : 'Scope unavailable'}</span><span className={`healthy ${apiOnline === false ? 'offline' : ''}`}><i /> API {apiOnline === null ? 'checking' : apiOnline ? 'online' : 'offline'}</span></div>
      </header>
      {children}
    </main>
  </div>
}
