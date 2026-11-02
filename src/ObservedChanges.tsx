import type { Stage } from './types';
import {ColumnOrigin} from './ColumnOrigin';
import type { TableChanges } from './tableChanges';

export function ObservedChanges({ stage, changes }: { stage: Stage; changes: TableChanges | null }) {
  if (!changes || !stage.input) return null;
  const d = changes;
  return <div className="observed-changes" aria-label="Step 입력 출력의 실제 변화">
    <span className="observed-size">{(stage.inputs?.length || 1) > 1 && `첫 입력(총 ${stage.inputs!.length}개) `}{stage.input.rows.length}행 × {stage.input.columns.length}열 → {stage.table.rows.length}행 × {stage.table.columns.length}열</span>
    {d.addedColumns.map(column=><ColumnOrigin key={stage.execution_version+':'+column} stage={stage} column={column}/>)}
    {d.removedColumns.length > 0 && <span className="delta-removed">− {d.removedColumns.join(', ')} 열</span>}
    {d.retypedColumns.length > 0 && <span className="delta-modified">타입 {d.retypedColumns.map(c=>`${c}: ${stage.input!.stats.fields[c]?.dtype} → ${stage.table.stats.fields[c]?.dtype}`).join(', ')}</span>}
    {d.rowIdentity && d.removedRows.length > 0 && <span className="delta-removed">− {d.removedRows.length}행</span>}
    {d.changedCells.size > 0 && <span className="delta-modified">값 변경 {d.changedCells.size}셀 · {d.changedRows.size}행</span>}
    {d.movedRows.size > 0 && <span className="delta-moved">순서 변경 {d.movedRows.size}행</span>}
    {d.columnsReordered && <span className="delta-moved">열 순서 변경</span>}
    {!d.rowIdentity && <span className="delta-unmapped">{d.rowsDelta > 0 ? `행 수 +${d.rowsDelta} · ` : d.rowsDelta < 0 ? `행 수 ${d.rowsDelta} · ` : ''}개별 행 대응 미표시</span>}
  </div>;
}
