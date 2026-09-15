export type Metric = {label:string; value:string; status?:'good'|'warn'|'bad'|'neutral'; delta?:string}
export type Narration = {title:string; summary:string; bullets:string[]; tone:'good'|'warn'|'bad'|'neutral'}
