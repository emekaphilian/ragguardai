import { useEffect, useState } from 'react'
import { getAuthSession, logout, startLogin, type AuthSession } from './api/client'
import Layout from './components/Layout'
import RecoverySummary from './components/RecoverySummary'
import Generic from './pages/Generic'
import Operations from './pages/Operations'
import Overview from './pages/Overview'
import QueryLab from './pages/QueryLabExperience'
import Runs from './pages/Runs'
import Recoveries from './pages/Recoveries'
import ConnectApplication from './pages/ConnectApplication'

type OperationsView = 'failures' | 'escalations' | 'strategies' | 'applications' | 'audit' | 'capabilities'

export default function App() {
  const [auth, setAuth] = useState<AuthSession | null>(null)
  const [authError, setAuthError] = useState('')
  const [authLoading, setAuthLoading] = useState(true)
  const [page, setPage] = useState('overview')
  const [recoverySearch, setRecoverySearch] = useState('')
  const [recoveryStatus, setRecoveryStatus] = useState('all')
  const openRecoveries = (search = '', status = 'all') => {
    setRecoverySearch(search)
    setRecoveryStatus(status)
    setPage('recoveries')
  }

  useEffect(() => {
    getAuthSession()
      .then(setAuth)
      .catch((error: unknown) => setAuthError(error instanceof Error ? error.message : 'Could not verify sign-in.'))
      .finally(() => setAuthLoading(false))
  }, [])

  if (authLoading) return <main className="auth-screen"><p>Checking sign-in…</p></main>
  if (authError) return <main className="auth-screen"><h1>RAGGuard sign-in unavailable</h1><p role="alert">{authError}</p></main>
  if (auth?.authentication_required && !auth.authenticated) return <main className="auth-screen"><h1>RAGGuard</h1><p>Sign in with your organization account to access your workspace.</p><button className="primary" onClick={startLogin}>Sign in</button></main>

  let content
  if (page === 'overview') {
    content = <><Overview /><RecoverySummary onOpenRecoveries={() => openRecoveries()} /></>
  } else if (page === 'query') {
    content = <QueryLab />
  } else if (page === 'runs') {
    content = <Runs />
  } else if (page === 'connect') {
    content = <ConnectApplication />
  } else if (page === 'recoveries') {
    content = <Recoveries key={`${recoverySearch}:${recoveryStatus}`} initialSearch={recoverySearch} initialStatusFilter={recoveryStatus} />
  } else if (['failures', 'escalations', 'strategies', 'applications', 'audit', 'capabilities'].includes(page)) {
    content = <Operations view={page as OperationsView} onOpenRecoveries={openRecoveries} />
  } else {
    content = <Generic type={page} />
  }

  return <><div className="auth-bar">{auth?.authenticated && <><span>Signed in as {auth.subject}{auth.administrator ? ' · Administrator' : ''}</span><button className="ghost" onClick={() => void logout().then(() => window.location.reload())}>Sign out</button></>}</div><Layout page={page} setPage={setPage}>{content}</Layout></>
}
