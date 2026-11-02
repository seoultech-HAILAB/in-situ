import type { Row, Stage } from './types';

export type TableChanges = {
  addedColumns: string[]; removedColumns: string[]; retypedColumns: string[];
  changedCells: Set<string>; changedRows: Set<string>; movedRows: Set<string>;
  removedRows: Row[]; rowIdentity: boolean; rowsDelta: number; columnsReordered: boolean;
};
export const cellKey = (row: string, column: string) => JSON.stringify([row, column]);

// Observation IDs in common tracing are NOT row correspondence. Never match by
// position or by coincidentally equal values (especially after joins/aggregation).
export function tableChanges(stage: Stage): TableChanges | null {
  const input = stage.input, output = stage.table;
  if (!input || stage.kind === 'input') return null;
  const addedColumns = output.columns.filter(c => !input.columns.includes(c));
  const removedColumns = input.columns.filter(c => !output.columns.includes(c));
  const common = output.columns.filter(c => input.columns.includes(c));
  const before = new Map(input.rows.map((r, i) => [r.id, { row: r, index: i }]));
  // These are the only adapters that preserve individual input-row identities.
  const preserving = new Set(['filter','derive','select','drop','rename','sort_values','astype',
    'fillna','dropna','drop_duplicates','replace','reset_index','copy','head','tail']);
  const members = !stage.view_operation_id && stage.operations?.length ? stage.operations : [stage];
  const rowIdentity = stage.trace_level === 'detailed' && members.every(op => preserving.has(op.kind)) &&
    (stage.inputs?.length || 1) === 1 && output.rows.every(r => before.has(r.id));
  const changedCells = new Set<string>(), changedRows = new Set<string>(), movedRows = new Set<string>();
  if (rowIdentity) for (const row of output.rows) {
    const old = before.get(row.id)!.row;
    for (const c of common) if (JSON.stringify(old.values[c]) !== JSON.stringify(row.values[c])) {
      changedCells.add(cellKey(row.id,c)); changedRows.add(row.id);
    }
  }
  const outputIds = new Set(output.rows.map(r => r.id));
  const survivingBefore = input.rows.filter(r => outputIds.has(r.id));
  if (rowIdentity) output.rows.forEach((r,i) => { if (survivingBefore[i]?.id !== r.id) movedRows.add(r.id); });
  return { addedColumns, removedColumns, changedCells, changedRows, movedRows, rowIdentity,
    removedRows: rowIdentity ? input.rows.filter(r => !outputIds.has(r.id)) : [],
    retypedColumns: common.filter(c => input.stats.fields[c]?.dtype !== output.stats.fields[c]?.dtype),
    rowsDelta: output.rows.length - input.rows.length,
    columnsReordered: !addedColumns.length && !removedColumns.length && input.columns.some((c,i) => output.columns[i] !== c) };
}

// Meaning labels come from verified tracing; generic Python keeps a neutral title.
export function conciseOperation(stage: Stage): string {
  if (stage.kind === 'input') return '입력 테이블';
  if (stage.trace_level === 'common') return stage.kind === 'setup' ? '실행 준비 · 표 유지' : 'Python 변환';
  if (stage.operations && stage.operations.length > 1 && !stage.view_operation_id) {
    const meaningful=stage.operations.filter(op=>op.kind !== 'copy' && op.kind !== 'reset_index');
    if (meaningful.length && meaningful.every(op=>['select','drop','rename','astype'].includes(op.kind))) return '열 정리';
    return [...new Set((meaningful.length ? meaningful : stage.operations).map(op => conciseOperation({...op,operations:undefined})))].join(' · ');
  }
  if (stage.kind === 'aggregate') return `${stage.params.keys?.join('·') || '그룹'}별 집계`;
  if (stage.kind === 'derive') return `${Object.keys(stage.params.formulas || {}).join('·') || '계산 열'} 계산`;
  return stage.label.split(' 적용 인자:')[0].replace(/ 연산$/, '');
}

// Imported syntactic boundaries have placeholder names such as 관찰 단계 2.
// These must not replace the meaningful names available from actual operations.
export function stepTitle(stage: Stage): string {
  if (stage.kind === 'input') return stage.label || '입력 테이블';
  const intent=stage.intent_label?.trim() || '';
  const placeholder=/^(?:(?:관찰|실행|검수|변환)\s*단계|step|stage|Python\s*변환)(?:\s*[-:#]?\s*\d+)?[.\s]*$/iu;
  if (!stage.view_operation_id && intent && !placeholder.test(intent)) return intent;
  const label=conciseOperation(stage);
  return label === 'Python 변환' ? `Step ${stage.order} 변환` : label;
}

export function focusWindow<T>(items: T[], index: number): T[] {
  const start = Math.max(0, Math.min(index - 1, items.length - 3));
  return items.slice(start, start + 3);
}
