import { useEffect, useState } from 'react'
import { getRecoveries } from '../api/client'
import { Section } from './Cards'
import type { RecoveryAuditRecord } from '../types'
import '../styles/recovery.css'

function formatDuration(milliseconds: number) {
  const elapsed = Math.max(
    0,
    milliseconds,
  )
  return elapsed < 1000 ? `${Math.round(elapsed)} ms` : `${(elapsed / 1000).toFixed(1)} s`
}

function duration(record: RecoveryAuditRecord) {
  if (!record.completed_at) return 'In progress'
  return formatDuration(
    new Date(record.completed_at).getTime() - new Date(record.started_at).getTime(),
  )
}

function timestamp(value: string) {
  return new Date(value).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function RecoverySummary({ onOpenRecoveries }: { onOpenRecoveries: () => void }) {
  const [records, setRecords] = useState<RecoveryAuditRecord[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    getRecoveries(1, 20)
      .then((page) => setRecords(page.items))
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : 'Recovery audit is unavailable')
      })
  }, [])

  const completed = records.filter((record) => record.completed_at)
  const promoted = records.filter((record) => record.final_status === 'promoted').length
  const escalated = records.filter((record) => record.final_status === 'escalated').length
  const promotionRate = completed.length
    ? Math.round((promoted / completed.length) * 100)
    : null
  const averageDuration = completed.length
    ? completed.reduce((total, record) => {
        return total + Math.max(
          0,
          new Date(record.completed_at!).getTime() - new Date(record.started_at).getTime(),
        )
      }, 0) / completed.length
    : null

  return (
    <div className="recovery-overview">
      <Section title="Recovery operations">
        {error ? (
          <p className="recovery-muted">Recovery audit is unavailable: {error}</p>
        ) : (
          <>
            <div className="recovery-kpis">
              <div><span>Recent recovery runs</span><strong>{records.length}</strong></div>
              <div><span>Recent promotion rate</span><strong>{promotionRate === null ? '--' : `${promotionRate}%`}</strong></div>
              <div><span>Escalated</span><strong>{escalated}</strong></div>
              <div><span>Average duration</span><strong>{averageDuration === null ? '--' : formatDuration(averageDuration)}</strong></div>
            </div>
            {records.length ? (
              <div className="recovery-activity">
                {records.slice(0, 4).map((record) => (
                  <div className="recovery-activity-row" key={record.recovery_id}>
                    <span className={`recovery-dot ${record.final_status}`} />
                    <span className="recovery-activity-main">
                      <strong>{record.failure_type || 'Recovery'} · {record.final_status}</strong>
                      <small>{record.application_id || 'Unknown app'} · {record.environment || 'Unknown environment'}</small>
                    </span>
                    <time>{timestamp(record.started_at)}</time>
                  </div>
                ))}
              </div>
            ) : (
              <p className="recovery-muted">No recovery records have been captured yet.</p>
            )}
            <button className="ghost recovery-open" onClick={onOpenRecoveries}>
              Open recovery runs <span aria-hidden="true">→</span>
            </button>
          </>
        )}
      </Section>
    </div>
  )
}
