import type {Stage} from './types';
import {workflowInputs} from './workflowGraph';
import {cellKey} from './tableChanges';

// Membership comes exclusively from the executed detailed adapter. Never group
// rows by equal displayed values or by the desired Target.
export function reviewGroups(stage:Stage){
  const empty={inputRows:{} as Record<string,number>,outputCells:{} as Record<string,number>,groups:[] as {index:number;label:string}[]};
  const inputs=workflowInputs(stage);
  if(stage.trace_level!=='detailed'||inputs.length!==1)return empty;
  const ids=new Set(inputs[0].table.rows.map(row=>row.id)),claimed=new Set<string>();
  const result={inputRows:{} as Record<string,number>,outputCells:{} as Record<string,number>,groups:[] as {index:number;label:string}[]};
  for(const row of stage.table.rows){
    const entries=Object.entries(stage.contexts?.[row.id]||{}).filter(([column,ctx])=>stage.table.columns.includes(column)&&['sum','mean','min','max','count','size','nunique','median','first','last','prod'].includes(ctx.operation));
    if(!entries.length)continue;
    const members=entries[0][1].member_rows;
    if(!members.length||members.some(id=>!ids.has(id)||claimed.has(id))||entries.some(([,ctx])=>JSON.stringify(ctx.member_rows)!==JSON.stringify(members)))return empty;
    const index=result.groups.length;
    result.groups.push({index,label:Object.entries(entries[0][1].group_keys).map(([key,value])=>`${key}: ${value??'∅'}`).join(' · ')||'전체 행'});
    for(const id of members){result.inputRows[id]=index;claimed.add(id);}
    for(const [column]of entries)result.outputCells[cellKey(row.id,column)]=index;
  }
  return result;
}

export const groupColor=(index:number)=>`hsl(${Math.round(index*137.508+207)%360} 85% 92%)`;
export const groupBorder=(index:number)=>`hsl(${Math.round(index*137.508+207)%360} 75% 43%)`;
