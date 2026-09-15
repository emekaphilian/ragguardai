const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'

export async function getDashboard(){
  const r=await fetch(`${API_BASE}/dashboard`); if(!r.ok) throw new Error('Dashboard unavailable'); return r.json()
}
export async function narrate(page:string, data:unknown){
  const r=await fetch(`${API_BASE}/narrate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page,data})})
  if(!r.ok) throw new Error('Narrator unavailable'); return r.json()
}
export async function runQuery(query:string, top_k=5, method='hybrid'){
  const r=await fetch(`${API_BASE}/query`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,top_k,method})})
  if(!r.ok) throw new Error('Query failed'); return r.json()
}
export async function getDocuments(){const r=await fetch(`${API_BASE}/documents`);if(!r.ok)throw new Error('Documents unavailable');return r.json()}
export async function addDocument(name:string,text:string){const r=await fetch(`${API_BASE}/documents`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,text})});if(!r.ok)throw new Error('Could not add document');return r.json()}
export async function getRuns(){const r=await fetch(`${API_BASE}/runs`);if(!r.ok)throw new Error('Runs unavailable');return r.json()}
export async function getFailures(){const r=await fetch(`${API_BASE}/failures`);if(!r.ok)throw new Error('Failures unavailable');return r.json()}
