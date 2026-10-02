import {useEffect,useState} from 'react'
import {narrate} from '../api/client'
import type {Narration} from '../types'

type NarrationPayload = Narration & {available?: boolean}
const metricFields=['context_precision','context_recall','faithfulness','answer_relevancy','citation_accuracy','failure_rate','repair_success_rate']
function hasLiveTelemetry(data:any){const metrics=data?.metrics||data||{};return metricFields.some(field=>typeof metrics[field]==='number'&&Number.isFinite(metrics[field]))}

function factualObservationSummary(page:string,data:any):Narration|null{
  if(page!=='Overview'||typeof data?.observation_runs!=='number')return null
  const total=Math.max(0,data.observation_runs)
  const failures=Math.max(0,Math.min(total,Number(data.observation_failures)||0))
  const healthy=total-failures
  const rate=total?Math.round(failures/total*100):0
  const requestLabel=total===1?'observed request':'observed requests'
  const application = data?.scope?.application_id || 'selected application'
  const tenant = data?.scope?.ragguard_tenant_id
  return {
    title:`${application} reliability snapshot`,
    summary:`RAGGuard detected reliability conditions in ${failures} of ${total} ${application} ${requestLabel} (${rate}%).${tenant ? ` Scope: RAGGuard tenant ${tenant}.` : ''}`,
    bullets:[`${healthy} ${healthy===1?'request was':'requests were'} classified as healthy.`,`A detected condition does not establish that an answer was incorrect.`],
    tone:failures?'warn':'good',
  }
}

export default function NarratorPanel({page,data}:{page:string;data:any}){
  const factualSummary=factualObservationSummary(page,data)
  const active=hasLiveTelemetry(data)&&!factualSummary
  const [n,setN]=useState<Narration|null>(null)
  const [loading,setLoading]=useState(false)
  useEffect(()=>{if(!active){setN(null);setLoading(false);return}let live=true;setLoading(true);narrate(page,data).then((payload:NarrationPayload)=>{if(live)setN(payload.available===false?null:payload)}).catch(()=>{if(live)setN(null)}).finally(()=>live&&setLoading(false));return()=>{live=false}},[page,JSON.stringify(data),active])
  if(factualSummary) return <section className={`narrator ${factualSummary.tone}`}><div className="narrator-mark">AI</div><div className="narrator-body"><div className="eyebrow">OBSERVED TELEMETRY · NO BASELINE INFERRED</div><h3>{factualSummary.title}</h3><p>{factualSummary.summary}</p><ul>{factualSummary.bullets.map((bullet,index)=><li key={index}>{bullet}</li>)}</ul></div></section>
  if(!active||(!n&&!loading)) return null
  if(loading&&!n) return <section className="narrator"><div className="narrator-mark">AI</div><div className="narrator-body"><div className="eyebrow">NARRATOR · ANALYZING LIVE TELEMETRY</div></div></section>
  if(!n) return null
  return <section className={`narrator ${n.tone}`}><div className="narrator-mark">AI</div><div className="narrator-body"><div className="eyebrow">NARRATOR · LIVE TELEMETRY</div><h3>{n.title}</h3><p>{n.summary}</p><ul>{n.bullets.map((b,i)=><li key={i}>{b}</li>)}</ul></div></section>
}
