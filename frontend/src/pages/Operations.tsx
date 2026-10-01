import { useEffect, useMemo, useState } from 'react'
import { getAllRecoveries, getFailures, getRepairCapabilities } from '../api/client'
import { Section } from '../components/Cards'
import type { RecoveryAuditEvent, RecoveryAuditRecord } from '../types'
import '../styles/recovery.css'

type Capability = { strategy: string; implemented: boolean; description: string }
type Props = {
  view: 'failures' | 'escalations' | 'strategies' | 'applications' | 'audit' | 'capabilities'
  onOpenRecoveries: (search?: string, status?: string) => void
}

function display(value: string) {
  return value.replace(/_/g, ' ').toLowerCase()
}

function date(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '--'
}

function ErrorMessage({ message }: { message: string }) {
  return <div className="recovery-error" role="alert">{message}</div>
}

function useRecoveryRecords() {
  const [records, setRecords] = useState<RecoveryAuditRecord[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getAllRecoveries()
      .then(setRecords)
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load recovery audit'))
      .finally(() => setLoading(false))
  }, [])

  return { records, error, loading }
}

function FailureView({ records, onOpenRecoveries }: { records: RecoveryAuditRecord[]; onOpenRecoveries: Props['onOpenRecoveries'] }) {
  const [activityFailures, setActivityFailures] = useState<any[]>([])
  const [activityError, setActivityError] = useState('')

  useEffect(() => {
    getFailures()
      .then(setActivityFailures)
      .catch((reason) => setActivityError(reason instanceof Error ? reason.message : 'Could not load failures'))
  }, [])

  const groups = useMemo(() => {
    const distinct = new Map<string, { failure: string; application_id?: string; created_at: string }>()
    records.forEach((record) => distinct.set(record.failure_id || record.recovery_id, {
      failure: record.failure_type || 'UNKNOWN',
      application_id: record.application_id || undefined,
      created_at: record.started_at,
    }))
    activityFailures.forEach((failure) => distinct.set(failure.id, {
      failure: failure.type || 'UNKNOWN',
      application_id: failure.application_id,
      created_at: failure.created_at,
    }))

    const occurrenceGroups = new Map<string, { count: number; applications: Set<string>; times: string[] }>()
    distinct.forEach((failure) => {
      const group = occurrenceGroups.get(failure.failure) || { count: 0, applications: new Set<string>(), times: [] }
      group.count += 1
      if (failure.application_id) group.applications.add(failure.application_id)
      group.times.push(failure.created_at)
      occurrenceGroups.set(failure.failure, group)
    })
    return [...occurrenceGroups.entries()]
      .map(([failure, group]) => ({
        failure,
        count: group.count,
        applications: group.applications.size,
        first: group.times.reduce((earliest, time) => time < earliest ? time : earliest, group.times[0]),
        last: group.times.reduce((latest, time) => time > latest ? time : latest, group.times[0]),
      }))
      .sort((a, b) => b.count - a.count)
  }, [records, activityFailures])

  return (
    <Section title="Failure patterns">
      <p className="operations-note">Counts include observed failures and recovery history; healthy observations are excluded.</p>
      {activityError && <ErrorMessage message={activityError} />}
      {groups.length ? <div className="operations-table-wrap"><table className="operations-table">
        <thead><tr><th>Failure type</th><th>Occurrences</th><th>Applications</th><th>First seen</th><th>Last seen</th><th /></tr></thead>
        <tbody>{groups.map((group) => <tr key={group.failure}>
          <td>{display(group.failure)}</td><td>{group.count}</td><td>{group.applications}</td>
          <td>{date(group.first)}</td><td>{date(group.last)}</td>
          <td><button className="ghost" onClick={() => onOpenRecoveries(group.failure)}>View recoveries</button></td>
        </tr>)}</tbody>
      </table></div> : <p className="operations-empty">No failed observations have recovery records yet.</p>}
    </Section>
  )
}

function EscalationView({ records, onOpenRecoveries }: { records: RecoveryAuditRecord[]; onOpenRecoveries: Props['onOpenRecoveries'] }) {
  const escalated = records.filter((record) => record.final_status === 'escalated')
  return <Section title={`Escalated recoveries · ${escalated.length}`}>
    <p className="operations-note">These runs ended without a promoted repair. Open a record to inspect its attempts and escalation events.</p>
    {escalated.length ? <div className="operations-table-wrap"><table className="operations-table">
      <thead><tr><th>Failure</th><th>Application</th><th>Environment</th><th>Attempts</th><th>Started</th><th /></tr></thead>
      <tbody>{escalated.map((record) => <tr key={record.recovery_id}>
        <td>{display(record.failure_type || 'unknown')}</td>
        <td>{record.application_id || '--'}</td><td>{record.environment || '--'}</td>
        <td>{record.attempts.length}</td><td>{date(record.started_at)}</td>
        <td><button className="ghost" onClick={() => onOpenRecoveries(record.recovery_id, 'escalated')}>Inspect</button></td>
      </tr>)}</tbody>
    </table></div> : <p className="operations-empty">No escalated recoveries.</p>}
  </Section>
}

function strategyDuration(record: RecoveryAuditRecord, attempt: number) {
  const started = record.events.find((event) => event.event_type === 'repair_started' && event.attempt === attempt)
  const finished = record.events.find((event) => event.event_type === 'repair_completed' && event.attempt === attempt)
  if (!started || !finished) return null
  return Math.max(0, new Date(finished.timestamp).getTime() - new Date(started.timestamp).getTime())
}

function StrategyView({ records }: { records: RecoveryAuditRecord[] }) {
  const rows = useMemo(() => {
    const grouped = new Map<string, { executed: number; promoted: number; rolledBack: number; changes: number[]; durations: number[] }>()
    records.forEach((record) => record.attempts.forEach((attempt, index) => {
      const row = grouped.get(attempt.strategy) || { executed: 0, promoted: 0, rolledBack: 0, changes: [], durations: [] }
      row.executed += 1
      if (attempt.status === 'promoted') row.promoted += 1
      if (attempt.status === 'rolled_back') row.rolledBack += 1
      if (typeof attempt.improvement === 'number') row.changes.push(attempt.improvement)
      const duration = strategyDuration(record, index + 1)
      if (duration !== null) row.durations.push(duration)
      grouped.set(attempt.strategy, row)
    }))
    return [...grouped.entries()].map(([strategy, row]) => ({ strategy, ...row }))
      .sort((a, b) => a.strategy.localeCompare(b.strategy))
  }, [records])

  return <Section title="Repair strategy outcomes">
    <p className="operations-note">Observed counts describe recorded attempts; they are not a strategy ranking.</p>
    {rows.length ? <div className="operations-table-wrap"><table className="operations-table">
      <thead><tr><th>Strategy</th><th>Executions</th><th>Promotions</th><th>Rollbacks</th><th>Mean score change</th><th>Mean execution time</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.strategy}>
        <td>{display(row.strategy)}</td><td>{row.executed}</td><td>{row.promoted}</td><td>{row.rolledBack}</td>
        <td>{row.changes.length ? (row.changes.reduce((sum, value) => sum + value, 0) / row.changes.length).toFixed(3) : '--'}</td>
        <td>{row.durations.length ? `${Math.round(row.durations.reduce((sum, value) => sum + value, 0) / row.durations.length)} ms` : '--'}</td>
      </tr>)}</tbody>
    </table></div> : <p className="operations-empty">No repair attempts have been recorded yet.</p>}
  </Section>
}

function ApplicationView({ records, onOpenRecoveries }: { records: RecoveryAuditRecord[]; onOpenRecoveries: Props['onOpenRecoveries'] }) {
  const groups = useMemo(() => {
    const grouped = new Map<string, RecoveryAuditRecord[]>()
    records.forEach((record) => {
      const key = `${record.application_id || 'unknown'}::${record.environment || 'unknown'}`
      grouped.set(key, [...(grouped.get(key) || []), record])
    })
    return [...grouped.entries()].map(([key, items]) => {
      const [application, environment] = key.split('::')
      const promoted = items.filter((item) => item.final_status === 'promoted').length
      return {
        application, environment, count: items.length, promoted,
        escalated: items.filter((item) => item.final_status === 'escalated').length,
        rate: items.length ? Math.round(promoted / items.length * 100) : 0,
      }
    }).sort((a, b) => a.application.localeCompare(b.application) || a.environment.localeCompare(b.environment))
  }, [records])

  return <Section title="Observed applications">
    <p className="operations-note">These are recovery counts, not total query volume. Source tenants remain separate from RAGGuard access tenants.</p>
    {groups.length ? <div className="operations-table-wrap"><table className="operations-table">
      <thead><tr><th>Application</th><th>Environment</th><th>Recoveries</th><th>Promotion rate</th><th>Escalated</th><th /></tr></thead>
      <tbody>{groups.map((group) => <tr key={`${group.application}:${group.environment}`}>
        <td>{group.application}</td><td>{group.environment}</td><td>{group.count}</td><td>{group.rate}%</td>
        <td>{group.escalated}</td>
        <td><button className="ghost" onClick={() => onOpenRecoveries(group.application)}>View</button></td>
      </tr>)}</tbody>
    </table></div> : <p className="operations-empty">No application recovery records.</p>}
  </Section>
}

function AuditView({ records, onOpenRecoveries }: { records: RecoveryAuditRecord[]; onOpenRecoveries: Props['onOpenRecoveries'] }) {
  const [eventType, setEventType] = useState('all')
  const [application, setApplication] = useState('all')
  const [environment, setEnvironment] = useState('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const events = useMemo(() => records.flatMap((record) => record.events)
    .filter((event) => eventType === 'all' || event.event_type === eventType)
    .filter((event) => application === 'all' || event.application_id === application)
    .filter((event) => environment === 'all' || event.environment === environment)
    .filter((event) => !from || Date.parse(event.timestamp) >= new Date(from).getTime())
    .filter((event) => !to || Date.parse(event.timestamp) <= new Date(to).getTime())
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp)), [records, eventType, application, environment, from, to])
  const eventTypes = [...new Set(records.flatMap((record) => record.events.map((event) => event.event_type)))].sort()
  const applications = [...new Set(records.map((record) => record.application_id).filter((value): value is string => Boolean(value)))].sort()
  const environments = [...new Set(records.map((record) => record.environment).filter((value): value is string => Boolean(value)))].sort()

  return <Section title={`Recovery events · ${events.length}`}>
    <div className="operations-filters">
      <label>Event type<select value={eventType} onChange={(event) => setEventType(event.target.value)}>
        <option value="all">All events</option>{eventTypes.map((type) => <option key={type} value={type}>{display(type)}</option>)}
      </select></label>
      <label>Application<select value={application} onChange={(event) => setApplication(event.target.value)}>
        <option value="all">All applications</option>{applications.map((app) => <option key={app} value={app}>{app}</option>)}
      </select></label>
      <label>Environment<select value={environment} onChange={(event) => setEnvironment(event.target.value)}>
        <option value="all">All environments</option>{environments.map((value) => <option key={value} value={value}>{value}</option>)}
      </select></label>
      <label>From<input type="datetime-local" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
      <label>To<input type="datetime-local" value={to} onChange={(event) => setTo(event.target.value)} /></label>
    </div>
    {events.length ? <div className="operations-table-wrap"><table className="operations-table">
      <thead><tr><th>Time</th><th>Event</th><th>Application</th><th>Environment</th><th>RAGGuard tenant</th><th>Attempt / strategy</th><th>Outcome</th><th /></tr></thead>
      <tbody>{events.map((event: RecoveryAuditEvent) => <tr key={event.event_id}>
        <td>{date(event.timestamp)}</td><td>{display(event.event_type)}</td><td>{event.application_id || '--'}</td><td>{event.environment || '--'}</td>
        <td>{event.ragguard_tenant_id || '--'}</td>
        <td>{event.attempt ? `${event.attempt} · ${event.strategy || ''}` : event.strategy || '--'}</td>
        <td>{event.status ? display(event.status) : '--'}</td>
        <td><button className="ghost" onClick={() => onOpenRecoveries(event.recovery_id)}>Open run</button></td>
      </tr>)}</tbody>
    </table></div> : <p className="operations-empty">No events match these filters.</p>}
  </Section>
}

function CapabilityView() {
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    getRepairCapabilities().then(setCapabilities)
      .catch((reason) => setError(reason instanceof Error ? reason.message : 'Could not load repair capabilities'))
  }, [])
  return <Section title="Repair capabilities">
    <p className="operations-note">Implemented strategies can be selected by recovery policy. This view reports implementation availability, not tenant-specific authorization.</p>
    {error ? <ErrorMessage message={error} /> : <div className="capability-list">
      {capabilities.map((capability) => <article key={capability.strategy}>
        <span className={`capability-indicator ${capability.implemented ? 'implemented' : ''}`}>{capability.implemented ? '✓' : '—'}</span>
        <div><strong>{display(capability.strategy)}</strong><small>{capability.description}</small></div>
        <span className={`recovery-pill ${capability.implemented ? 'promoted' : 'rolled_back'}`}>{capability.implemented ? 'implemented' : 'unavailable'}</span>
      </article>)}
    </div>}
  </Section>
}

const titles: Record<Props['view'], string> = {
  failures: 'Failure intelligence',
  escalations: 'Escalation queue',
  strategies: 'Repair analytics',
  applications: 'Applications',
  audit: 'Audit explorer',
  capabilities: 'Repair capabilities',
}

export default function Operations({ view, onOpenRecoveries }: Props) {
  const { records, error, loading } = useRecoveryRecords()
  return <div className="page operations-page">
    <div className="recoveries-heading"><div><span className="recovery-eyebrow">RAGGUARD OPERATIONS</span><h2>{titles[view]}</h2></div></div>
    {error && <ErrorMessage message={error} />}
    {view !== 'capabilities' && <p className="operations-note">Aggregates include all recovery records visible to this tenant, loaded in pages.</p>}
    {loading ? <Section title="Loading"><p className="operations-note">Loading recovery audit data…</p></Section> : view === 'capabilities' ? <CapabilityView /> : view === 'failures' ? <FailureView records={records} onOpenRecoveries={onOpenRecoveries} /> : view === 'escalations' ? <EscalationView records={records} onOpenRecoveries={onOpenRecoveries} /> : view === 'strategies' ? <StrategyView records={records} /> : view === 'applications' ? <ApplicationView records={records} onOpenRecoveries={onOpenRecoveries} /> : <AuditView records={records} onOpenRecoveries={onOpenRecoveries} />}
  </div>
}
