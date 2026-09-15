import {useEffect,useState} from 'react'
import {narrate} from '../api/client'
import type {Narration} from '../types'

type NarrationPayload = Narration & {available?: boolean}
const metricFields=['context_precision','context_recall','faithfulness','answer_relevancy','citation_accuracy','failure_rate','repair_success_rate']
function hasLiveTelemetry(data:any){const metrics=data?.metrics||data||{};return metricFields.some(field=>typeof metrics[field]==='number'&&Number.isFinite(metrics[field]))}

export default function NarratorPanel({page,data}:{page:string;data:any}){
  const active=hasLiveTelemetry(data)
  const [n,setN]=useState<Narration|null>(null)
  const [loading,setLoading]=useState(false)
  useEffect(()=>{if(!active){setN(null);setLoading(false);return}let live=true;setLoading(true);narrate(page,data).then((payload:NarrationPayload)=>{if(live)setN(payload.available===false?null:payload)}).catch(()=>{if(live)setN(null)}).finally(()=>live&&setLoading(false));return()=>{live=false}},[page,JSON.stringify(data),active])
  if(!active||(!n&&!loading)) return null
  if(loading&&!n) return <section className="narrator"><div className="narrator-mark">AI</div><div className="narrator-body"><div className="eyebrow">NARRATOR · ANALYZING LIVE TELEMETRY</div></div></section>
  if(!n) return null
  return <section className={`narrator ${n.tone}`}><div className="narrator-mark">AI</div><div className="narrator-body"><div className="eyebrow">NARRATOR · LIVE TELEMETRY</div><h3>{n.title}</h3><p>{n.summary}</p><ul>{n.bullets.map((b,i)=><li key={i}>{b}</li>)}</ul></div></section>
}
