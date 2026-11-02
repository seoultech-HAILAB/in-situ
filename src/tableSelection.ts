import type {ReviewTarget,Table} from './types';

export const pointKey=(row_id:string,column:string)=>JSON.stringify([row_id,column]);
export function selectedCells(target:ReviewTarget|null|undefined,table:Table){
  if(!target||target.kind==='step')return [];
  if(target.kind==='cells'&&target.cells)return target.cells;
  const rows=target.kind==='cell'||target.kind==='row'?table.rows.filter(row=>row.id===target.row_id):target.row_ids?table.rows.filter(row=>target.row_ids!.includes(row.id)):table.rows;
  const columns=target.kind==='cell'||target.kind==='column'?table.columns.filter(column=>column===target.column):target.columns||table.columns;
  return rows.flatMap(row=>columns.map(column=>({row_id:row.id,column})));
}
export function sameSelectionTable(a:ReviewTarget,b:ReviewTarget){
  return a.step_id===b.step_id&&a.operation_id===b.operation_id&&(a.table_role||'output')===(b.table_role||'output')&&a.input_ref===b.input_ref&&!!a.removed===!!b.removed;
}
export function combineSelection(previous:ReviewTarget|null|undefined,next:ReviewTarget,table:Table,toggle=true):ReviewTarget|null{
  const points=new Map((previous&&sameSelectionTable(previous,next)?selectedCells(previous,table):[]).map(cell=>[pointKey(cell.row_id,cell.column),cell]));
  const incoming=selectedCells(next,table),remove=toggle&&incoming.every(cell=>points.has(pointKey(cell.row_id,cell.column)));
  for(const cell of incoming){const key=pointKey(cell.row_id,cell.column);if(remove)points.delete(key);else points.set(key,cell);}
  if(!points.size)return null;
  return {kind:'cells',step_id:next.step_id,operation_id:next.operation_id,table_role:next.table_role,input_ref:next.input_ref,removed:next.removed,cells:[...points.values()]};
}
