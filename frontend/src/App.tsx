import { useState } from 'react'
import Layout from './components/Layout'
import RecoverySummary from './components/RecoverySummary'
import Generic from './pages/Generic'
import Operations from './pages/Operations'
import Overview from './pages/Overview'
import QueryLab from './pages/QueryLab'
import Runs from './pages/Runs'
import Recoveries from './pages/Recoveries'

type OperationsView = 'failures' | 'escalations' | 'strategies' | 'applications' | 'audit' | 'capabilities'

export default function App() {
  const [page, setPage] = useState('overview')
  const [recoverySearch, setRecoverySearch] = useState('')
  const [recoveryStatus, setRecoveryStatus] = useState('all')
  const openRecoveries = (search = '', status = 'all') => {
    setRecoverySearch(search)
    setRecoveryStatus(status)
    setPage('recoveries')
  }

  let content
  if (page === 'overview') {
    content = <><Overview /><RecoverySummary onOpenRecoveries={() => openRecoveries()} /></>
  } else if (page === 'query') {
    content = <QueryLab />
  } else if (page === 'runs') {
    content = <Runs />
  } else if (page === 'recoveries') {
    content = <Recoveries key={`${recoverySearch}:${recoveryStatus}`} initialSearch={recoverySearch} initialStatusFilter={recoveryStatus} />
  } else if (['failures', 'escalations', 'strategies', 'applications', 'audit', 'capabilities'].includes(page)) {
    content = <Operations view={page as OperationsView} onOpenRecoveries={openRecoveries} />
  } else {
    content = <Generic type={page} />
  }

  return <Layout page={page} setPage={setPage}>{content}</Layout>
}
