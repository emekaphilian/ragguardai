import { useEffect, useRef, useState } from 'react'
import NarratorPanel from '../components/NarratorPanel'
import { Section } from '../components/Cards'
import { addDocument, deleteDocument, getDocuments, getFailures, getRuns, uploadDocument } from '../api/client'

const accepted = '.txt,.md,.markdown,.rst,.csv,.tsv,.json,.yaml,.yml,.xml,.html,.htm,.pdf,.docx,.xlsx,.xlsm,.pptx,.py,.js,.ts,.tsx,.sql,.log'
const REFRESH_MS = 4000

type ActivityRun = {
  id: string
  query: string
  status: string
  method?: string
  latency_ms?: number
  created_at: string
  application_id?: string
  environment?: string
  retrieved_count?: number
  top_score?: number | null
  failure_type?: string | null
  recovery_status?: string | null
}

function RunsView({ items, loading, error }: { items: ActivityRun[]; loading: boolean; error: string }) {
  return <>
    {error && <p className="activity-error" role="alert">{error}</p>}
    {loading && items.length === 0 ? <p className="answer">Loading recent activity…</p> : items.length ? <div className="operations-table-wrap"><table className="operations-table">
      <thead><tr><th>Time</th><th>Application / environment</th><th>Query</th><th>Status</th><th>Retrieval</th><th>Chunks</th><th>Top score</th><th>Latency</th></tr></thead>
      <tbody>{items.map((run) => <tr key={run.id}>
        <td>{new Date(run.created_at).toLocaleString()}</td>
        <td>{run.application_id ? `${run.application_id} · ${run.environment || 'unknown'}` : 'RAGGuard workspace'}</td>
        <td className="activity-query">{run.query}</td>
        <td><span className={`recovery-pill ${run.status === 'healthy' || run.status === 'grounded' || run.status === 'promoted' ? 'promoted' : run.status === 'escalated' || run.status === 'failure' || run.status === 'no_match' ? 'rolled_back' : ''}`}>{run.status}</span>
          {run.failure_type && <small className="activity-subline">{run.failure_type.replace(/_/g, ' ')}</small>}
        </td>
        <td>{run.method || 'unknown'}</td><td>{run.retrieved_count ?? '—'}</td>
        <td>{typeof run.top_score === 'number' ? run.top_score.toFixed(3) : '—'}</td>
        <td>{typeof run.latency_ms === 'number' ? `${Math.round(run.latency_ms)} ms` : '—'}</td>
      </tr>)}</tbody>
    </table></div> : <p className="answer">No query activity has been recorded for this RAGGuard tenant.</p>}
    <p className="activity-refresh-note">Refreshes every {REFRESH_MS / 1000} seconds. Observation history is stored separately from workspace queries.</p>
  </>
}

function FailureView({ items, loading, error }: { items: any[]; loading: boolean; error: string }) {
  if (error) return <p className="activity-error" role="alert">{error}</p>
  if (loading && items.length === 0) return <p className="answer">Loading failures…</p>
  return items.length ? <div className="failure-list">{items.map((failure) => <article key={failure.id}>
    <b>{failure.type} <span className="failure-state">{failure.status}</span></b>
    <span>{failure.application_id ? `${failure.application_id} · ${failure.environment || 'unknown'} · ` : ''}{failure.severity} · {failure.query}</span>
    <small>{new Date(failure.created_at).toLocaleString()}</small>
  </article>)}</div> : <p className="answer">No failures have been recorded for this RAGGuard tenant.</p>
}

export default function Generic({ type }: { type: string }) {
  const [items, setItems] = useState<any[]>([])
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [pendingDelete, setPendingDelete] = useState<any>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const loader = type === 'documents' ? getDocuments : type === 'failures' ? getFailures : type === 'runs' ? getRuns : null

  useEffect(() => {
    let active = true
    const refresh = () => loader?.()
      .then((result) => { if (active) { setItems(result); setError('') } })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : 'Could not load activity') })
      .finally(() => { if (active) setLoading(false) })

    void refresh()
    const timer = type === 'runs' || type === 'failures' ? window.setInterval(() => { void refresh() }, REFRESH_MS) : undefined
    return () => { active = false; if (timer !== undefined) window.clearInterval(timer) }
  }, [type])

  const save = async () => {
    if (!text.trim()) return
    try {
      setError(''); setBusy(true)
      const created = await addDocument(name.trim() || 'Pasted text', text)
      if (type === 'documents') setItems((current) => [created, ...current.filter((item) => item.id !== created.id)])
      setName(''); setText('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not add document') }
    finally { setBusy(false) }
  }

  const upload = async (file?: File) => {
    if (!file) return
    try {
      setError(''); setBusy(true)
      const created = await uploadDocument(file)
      setItems((current) => [created, ...current.filter((item) => item.id !== created.id)])
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not upload document') }
    finally { setBusy(false); if (fileInput.current) fileInput.current.value = '' }
  }

  const remove = async (item: any) => {
    try {
      setError(''); setBusy(true); await deleteDocument(item.id)
      setItems((current) => current.filter((row) => row.id !== item.id)); setPendingDelete(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not delete document') }
    finally { setBusy(false) }
  }

  const title = type === 'documents' ? 'Documents' : type === 'failures' ? 'Failures' : type === 'runs' ? 'Query Runs' : `${type[0].toUpperCase()}${type.slice(1)}`
  return <div className="page">
    <NarratorPanel page={title} data={{ items }} />
    <Section title={title}>
      {type === 'documents' && <div className="upload">
        <div className="upload-actions"><button className="primary" onClick={() => fileInput.current?.click()} disabled={busy}>Upload document</button><input ref={fileInput} type="file" accept={accepted} hidden onChange={(event) => void upload(event.target.files?.[0])} /><span className="upload-hint">PDF, DOCX, XLSX, PPTX, TXT, Markdown and common text formats</span></div>
        <input placeholder="Document name (optional)" value={name} onChange={(event) => setName(event.target.value)} />
        <textarea placeholder="Or paste source text to index it…" value={text} onChange={(event) => setText(event.target.value)} />
        <button className="primary" onClick={() => void save()} disabled={busy || !text.trim()}>{busy ? 'Indexing…' : 'Index pasted text'}</button>
      </div>}
      {error && type === 'documents' && <p className="activity-error" role="alert">{error}</p>}
      {type === 'runs' ? <RunsView items={items} loading={loading} error={error} /> : type === 'failures' ? <FailureView items={items} loading={loading} error={error} /> : <div className="run-list">
        {items.length ? items.map((item: any) => <article className="document-row" key={item.id}>
          <div className="document-row-head"><strong>{item.source}</strong><span className="status good">{item.status || 'indexed'}</span></div>
          <div className="document-details"><span>Source <b>{item.ingestion_method || 'integration'}</b></span><span>Chunks <b>{item.chunks}</b></span><span>Characters <b>{item.characters}</b></span><span>Embedding <b>{item.embedding_model || 'local-tfidf'}</b></span><span>Dimensions <b>{item.embedding_dimensions ?? 'Unavailable'}</b></span><span>Vectors <b>{item.embedding_vectors ?? item.chunks}</b></span></div>
          <small>{item.id}</small><div className="document-actions">{pendingDelete?.id === item.id ? <div className="delete-warning" role="alert"><strong>Delete this indexed document permanently?</strong><span>This removes the document and all its chunks and vectors from the index. This cannot be undone.</span><button className="danger" onClick={() => void remove(item)} disabled={busy}>Delete permanently</button><button className="ghost" onClick={() => setPendingDelete(null)} disabled={busy}>Cancel</button></div> : <button className="danger-outline" onClick={() => setPendingDelete(item)} disabled={busy}>Delete</button>}</div>
        </article>) : <p className="answer">{loading ? 'Loading documents…' : 'No documents indexed yet.'}</p>}
      </div>}
    </Section>
  </div>
}
