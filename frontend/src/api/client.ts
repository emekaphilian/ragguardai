import type { RecoveryAuditPage, RecoveryAuditRecord } from '../types'

export type RepairCapability = { strategy: string; implemented: boolean; description: string }
export type ApiHealth = { status: string; service: string }
export type RegisteredApplication = {
  application_id: string
  display_name: string
  environment: string
  knowledge_source: 'managed_index' | 'external_rag_api' | 'observation_only'
  active: boolean
  queryable: boolean
  observation_enabled: boolean
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'
export const RAGGUARD_TENANT_ID = import.meta.env.VITE_RAGGUARD_TENANT_ID?.trim() || ''

function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (RAGGUARD_TENANT_ID) headers.set('X-RAGGuard-Tenant', RAGGUARD_TENANT_ID)
  return fetch(`${API_BASE}${path}`, { ...init, headers })
}

export async function getApiHealth(): Promise<ApiHealth> {
  const r = await apiFetch('/health')
  if (!r.ok) throw new Error('API health check failed')
  return r.json()
}

export async function getDashboard(){
  const r=await apiFetch('/dashboard'); if(!r.ok) throw new Error(await responseError(r, 'Dashboard unavailable'))
  const dashboard = await r.json()
  if (dashboard.scope?.ragguard_tenant_id && dashboard.scope?.application_id && dashboard.scope?.environment) return dashboard

  const observations = (dashboard.recent_runs || [])
    .filter((run: any) => (
      run.source !== 'workspace'
      && run.tenant_id
      && run.application_id
      && run.environment
    ))
    .sort((left: any, right: any) => (
      new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
    ))
  const latest = observations[0]
  if (latest) {
    dashboard.scope = {
      ragguard_tenant_id: latest.tenant_id,
      application_id: latest.application_id,
      environment: latest.environment,
    }
  }
  return dashboard
}
export async function narrate(page:string, data:unknown){
  const r=await apiFetch('/narrate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page,data})})
  if(!r.ok) throw new Error('Narrator unavailable'); return r.json()
}
export async function runQuery(query:string, top_k=5, method='hybrid', recordRun=false, applicationId?:string, environment?:string){
  const r=await apiFetch('/query',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query,top_k,method,record_run:recordRun,application_id:applicationId,environment})
  })
  if(!r.ok) throw new Error(await responseError(r, 'Query test failed'))
  const result = await r.json()
  if(!result.reliability_evaluation || !Object.prototype.hasOwnProperty.call(result, 'reliability_failure')){
    throw new Error('The API deployment does not support Query Lab reliability evaluation yet. Deploy the updated RAGGuard API before running controlled tests.')
  }
  return result
}
export async function runRepair(query:string,answer:string,relevantChunkIds:string[],top_k=5,applicationId?:string,environment?:string){
  const r=await apiFetch('/repair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,answer,relevant_chunk_ids:relevantChunkIds,top_k,application_id:applicationId,environment})})
  if(!r.ok)throw new Error(await responseError(r,'Repair test failed'))
  return r.json()
}
export async function getDocuments(){const r=await apiFetch('/documents');if(!r.ok)throw new Error('Documents unavailable');return r.json()}
export async function getApplications():Promise<RegisteredApplication[]>{const r=await apiFetch('/applications');if(r.status===404)throw new Error('The configured API does not provide the application registry endpoint (GET /api/v1/applications). Deploy the current RAGGuard API, then refresh this page.');if(!r.ok)throw new Error(await responseError(r,'Applications unavailable'));return r.json()}
export async function getRecycleBin(){const r=await apiFetch('/documents/recycle-bin');if(!r.ok)throw new Error('Recycle bin unavailable');return r.json()}
export async function addDocument(name:string,text:string){const r=await apiFetch('/documents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,text})});if(!r.ok)throw new Error('Could not add document');return r.json()}
export async function deleteDocument(id:string){const r=await apiFetch(`/documents/${encodeURIComponent(id)}`,{method:'DELETE'});if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Could not delete document')}return r.json()}
export async function restoreDocument(id:string){const r=await apiFetch(`/documents/recycle-bin/${encodeURIComponent(id)}/restore`,{method:'POST'});if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Could not restore document')}return r.json()}
export async function permanentlyDeleteDocument(id:string){const r=await apiFetch(`/documents/recycle-bin/${encodeURIComponent(id)}`,{method:'DELETE'});if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Could not permanently delete document')}return r.json()}
export async function uploadDocument(file:File){const body=new FormData();body.append('file',file);const r=await apiFetch('/documents/upload',{method:'POST',body});if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Could not upload document')}return r.json()}
export type RunFilters = {
  applicationId?: string
  environment?: string
  status?: string
  failureDetected?: boolean
}

export async function getRuns(limit=50,offset=0,filters:RunFilters={}){
  const params = new URLSearchParams({limit:String(limit),offset:String(offset)})
  if(filters.applicationId)params.set('application_id',filters.applicationId)
  if(filters.environment)params.set('environment',filters.environment)
  if(filters.status)params.set('status',filters.status)
  if(filters.failureDetected!==undefined)params.set('failure_detected',String(filters.failureDetected))
  const [runsResponse, dashboardResponse] = await Promise.all([
    apiFetch(`/runs?${params.toString()}`),
    apiFetch('/dashboard'),
  ])
  if(!runsResponse.ok)throw new Error(await responseError(runsResponse, 'Runs unavailable'))
  if(!dashboardResponse.ok)throw new Error(await responseError(dashboardResponse, 'Dashboard unavailable'))
  const dashboard = await dashboardResponse.json()
  if(!Object.prototype.hasOwnProperty.call(dashboard.metrics || {}, 'observation_runs')){
    throw new Error('The API deployment does not include application observation history yet. Deploy the updated RAGGuard API, then refresh this page.')
  }
  return runsResponse.json()
}
export async function getFailures(){const r=await apiFetch('/failures');if(!r.ok)throw new Error(await responseError(r, 'Failures unavailable'));return r.json()}
export async function getRecoveries(page=1,pageSize=50):Promise<RecoveryAuditPage>{const r=await apiFetch(`/recoveries?page=${page}&page_size=${pageSize}`);if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Recoveries unavailable')}return r.json()}
export async function getAllRecoveries(pageSize=50):Promise<RecoveryAuditRecord[]>{const records:RecoveryAuditRecord[]=[];let page=1;while(true){const result=await getRecoveries(page,pageSize);records.push(...result.items);if(!result.has_next)return records;page+=1}}
export async function getRecovery(recoveryId:string):Promise<RecoveryAuditRecord>{const r=await apiFetch(`/recoveries/${encodeURIComponent(recoveryId)}`);if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Recovery unavailable')}return r.json()}
export async function getRepairCapabilities():Promise<RepairCapability[]>{const r=await apiFetch('/repair-capabilities');if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Repair capabilities unavailable')}return r.json()}

async function responseError(response: Response, fallback: string) {
  const detail = await response.json().catch(() => null)
  return detail?.detail || `${fallback} (HTTP ${response.status})`
}
