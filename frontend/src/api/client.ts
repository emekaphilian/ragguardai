import type { RecoveryAuditPage, RecoveryAuditRecord } from '../types'

export type RepairCapability = { strategy: string; implemented: boolean; description: string }
export type ApiHealth = { status: string; service: string }

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
  const r=await apiFetch('/dashboard'); if(!r.ok) throw new Error(await responseError(r, 'Dashboard unavailable')); return r.json()
}
export async function narrate(page:string, data:unknown){
  const r=await apiFetch('/narrate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page,data})})
  if(!r.ok) throw new Error('Narrator unavailable'); return r.json()
}
export async function runQuery(query:string, top_k=5, method='hybrid'){
  const r=await apiFetch('/query',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({query,top_k,method})
  })
  if(!r.ok) throw new Error('Query failed')
  return r.json()
}
export async function getDocuments(){const r=await apiFetch('/documents');if(!r.ok)throw new Error('Documents unavailable');return r.json()}
export async function addDocument(name:string,text:string){const r=await apiFetch('/documents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,text})});if(!r.ok)throw new Error('Could not add document');return r.json()}
export async function deleteDocument(id:string){const r=await apiFetch(`/documents/${encodeURIComponent(id)}`,{method:'DELETE'});if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Could not delete document')}return r.json()}
export async function uploadDocument(file:File){const body=new FormData();body.append('file',file);const r=await apiFetch('/documents/upload',{method:'POST',body});if(!r.ok){const detail=await r.json().catch(()=>null);throw new Error(detail?.detail||'Could not upload document')}return r.json()}
export async function getRuns(limit=50,offset=0){
  const [runsResponse, dashboardResponse] = await Promise.all([
    apiFetch(`/runs?limit=${limit}&offset=${offset}`),
    apiFetch('/dashboard'),
  ])
  if(!runsResponse.ok)throw new Error(await responseError(runsResponse, 'Runs unavailable'))
  if(!dashboardResponse.ok)throw new Error(await responseError(dashboardResponse, 'Dashboard unavailable'))
  const dashboard = await dashboardResponse.json()
  if(!Object.prototype.hasOwnProperty.call(dashboard.metrics || {}, 'observation_runs')){
    throw new Error('The API deployment does not include TrustAssist observation history yet. Deploy the updated RAGGuard API, then refresh this page.')
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
