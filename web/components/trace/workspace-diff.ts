import type { CellValue, Row, Stage, Table } from "../../../src/types";

export type ChangeKind = "added" | "changed" | "removed";
export type DiffColumn = { name: string; kind?: ChangeKind };
export type DiffCell = { value: CellValue | undefined; before?: CellValue; after?: CellValue; kind?: ChangeKind };
export type DiffRow = { key: string; id: string; number: number; kind?: ChangeKind; cells: Record<string, DiffCell> };
export type WorkspaceDiff = { columns: DiffColumn[]; rows: DiffRow[]; before: Table | null; removedRows: number; removedColumns: number };
export type ChangeTarget = { kind: ChangeKind; row?: DiffRow; column?: string; cell?: DiffCell };
export type Transformation = { code: string; text: string; line?: { start: number; end: number } };

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const owns = (row: Row | undefined, column: string) => !!row && Object.hasOwn(row.values, column);

// Keep deleted items beside their next surviving neighbor. Output items always
// retain their executed order; deleted items never enter the actual result.
function withDeleted<T>(after: T[], before: T[], key: (item: T) => string): T[] {
  const kept = new Set(after.map(key));
  const buckets = new Map<string | null, T[]>();
  let next: string | null = null;
  for (let i = before.length - 1; i >= 0; i--) {
    const item = before[i];
    if (kept.has(key(item))) next = key(item);
    else buckets.set(next, [item, ...(buckets.get(next) || [])]);
  }
  return [...after.flatMap(item => [...(buckets.get(key(item)) || []), item]), ...(buckets.get(null) || [])];
}

export function comparisonInput(stage: Stage): Table | null {
  // A Step may also prepare a side table. Compare its output with the main
  // consumed table, rather than an unrelated first operation's table.
  const candidates = [stage.input, ...(stage.inputs || []).map(item => item.table)].filter((t): t is Table => !!t);
  const ids = new Set(stage.table.rows.map(row => row.id));
  const score = (table: Table) => [table.rows.filter(row => ids.has(row.id)).length, table.columns.filter(c => stage.table.columns.includes(c)).length];
  return candidates.reduce<Table | null>((best, table) => {
    if (!best) return table;
    const a = score(table), b = score(best);
    return a[0] > b[0] || (a[0] === b[0] && a[1] > b[1]) ? table : best;
  }, null);
}

export function workspaceDiff(stage: Stage): WorkspaceDiff {
  const before = comparisonInput(stage), after = stage.table;
  if (!before) return { before, columns: after.columns.map(name => ({ name })), rows: after.rows.map((row, i) => ({ key: row.id, id: row.id, number: i + 1, cells: Object.fromEntries(after.columns.map(c => [c, { value: row.values[c] }])) })), removedRows: 0, removedColumns: 0 };
  const oldRows = new Map(before.rows.map((row, i) => [row.id, { row, number: i + 1 }]));
  const outputIds = new Set(after.rows.map(row => row.id));
  const oldColumns = new Set(before.columns), outputColumns = new Set(after.columns);
  const columns: DiffColumn[] = withDeleted(after.columns, before.columns, c => c).map(name => ({ name,
    kind: !outputColumns.has(name) ? "removed" : !oldColumns.has(name) ? "added" : undefined }));
  // Observation IDs in untraced Python are not correspondence. Never align
  // unrelated rows by their position, coincidentally equal IDs, or cell values.
  const preserving = new Set(["filter", "derive", "select", "drop", "rename", "sort_values", "astype", "fillna", "dropna", "drop_duplicates", "replace", "reset_index", "copy", "head", "tail"]);
  const members = stage.operations?.length ? stage.operations : [stage];
  const hasIdentity = (stage.trace_level === "detailed" || stage.trace_level === "partial") && members.every(op => preserving.has(op.kind));
  const matched = (id: string) => hasIdentity ? oldRows.get(id) : undefined;
  const changedColumns = new Set<string>();
  for (const column of columns) if (!column.kind && before.stats.fields[column.name]?.dtype !== after.stats.fields[column.name]?.dtype) changedColumns.add(column.name);
  const retypedColumns = new Set(changedColumns);
  const oldOrder = before.columns.filter(c => outputColumns.has(c)), newOrder = after.columns.filter(c => oldColumns.has(c));
  newOrder.forEach((column, i) => { if (oldOrder[i] !== column) changedColumns.add(column); });
  const survivingBefore = before.rows.filter(row => outputIds.has(row.id));
  const survivingAfter = after.rows.filter(row => oldRows.has(row.id));
  const movedRows = new Set(hasIdentity ? survivingAfter.filter((row, i) => survivingBefore[i]?.id !== row.id).map(row => row.id) : []);
  const rows: DiffRow[] = after.rows.map((row, i) => {
    const old = matched(row.id)?.row;
    const cells: Record<string, DiffCell> = {};
    let changed = movedRows.has(row.id);
    for (const column of columns) {
      const c = column.name;
      if (column.kind === "removed") {
        cells[c] = old && owns(old, c) ? { value: old.values[c], before: old.values[c], kind: "removed" } : { value: undefined };
      } else if (!old || column.kind === "added") {
        cells[c] = { value: row.values[c], after: row.values[c], kind: "added" };
      } else {
        const inserted = !owns(old, c) && owns(row, c);
        const cleared = owns(old, c) && (!owns(row, c) || (old.values[c] != null && row.values[c] === null));
        const differs = !same(old.values[c], row.values[c]);
        const retyped = retypedColumns.has(c);
        cells[c] = { value: cleared ? old.values[c] : row.values[c], before: old.values[c], after: row.values[c], kind: cleared ? "removed" : inserted ? "added" : differs || retyped ? "changed" : undefined };
        if (differs || retyped) { changed = true; changedColumns.add(c); }
      }
    }
    return { key: `after:${row.id}`, id: row.id, number: i + 1, kind: !old ? "added" : changed ? "changed" : undefined, cells };
  });
  for (const column of columns) if (!column.kind && changedColumns.has(column.name)) column.kind = "changed";
  const removedRows: DiffRow[] = before.rows.filter(row => !hasIdentity || !outputIds.has(row.id)).map(row => ({
    key: `before:${row.id}`, id: row.id, number: oldRows.get(row.id)!.number, kind: "removed",
    cells: Object.fromEntries(columns.map(c => [c.name, owns(row, c.name) ? { value: row.values[c.name], before: row.values[c.name], kind: "removed" } : { value: undefined }])),
  }));
  const merged = hasIdentity ? withDeleted(rows, before.rows.map(row => removedRows.find(item => item.id === row.id) || rows.find(item => item.id === row.id)!), row => row.id) : [...rows, ...removedRows];
  return { before, columns, rows: merged, removedRows: removedRows.length, removedColumns: columns.filter(c => c.kind === "removed").length };
}

function operationAffects(operation: Stage, target: ChangeTarget): boolean {
  const input = operation.input, output = operation.table, column = target.column;
  if (!input) return false;
  if (!column && target.row?.kind === "removed") return input.rows.some(r => r.id === target.row!.id) && !output.rows.some(r => r.id === target.row!.id);
  if (!column && target.row?.kind === "added") return output.rows.some(r => r.id === target.row!.id) && !input.rows.some(r => r.id === target.row!.id);
  if (!column && target.row && operation.kind === "sort_values") return true;
  if (!column) return target.row ? Object.entries(target.row.cells).some(([name, cell]) => !!cell.kind && operationAffects(operation, { ...target, column: name, cell })) : false;
  if (target.row?.kind === "removed") return input.rows.some(r => r.id === target.row!.id) && !output.rows.some(r => r.id === target.row!.id);
  if (target.kind === "removed" && input.columns.includes(column) && !output.columns.includes(column)) return true;
  if (operation.params.formulas?.[column] || operation.params.aggregations?.[column]) return true;
  if (!input.columns.includes(column) && output.columns.includes(column)) return true;
  if (input.stats.fields[column]?.dtype !== output.stats.fields[column]?.dtype && output.columns.includes(column)) return true;
  return input.rows.some(old => {
    if (target.row && old.id !== target.row.id) return false;
    const row = output.rows.find(item => item.id === old.id);
    return !!row && !same(old.values[column], row.values[column]);
  });
}

function observedDescription(operation: Stage, target: ChangeTarget): string {
  const column = target.column;
  const described = column && operation.column_explanations?.[column];
  if (described) return described;
  if (operation.nl_explanation?.text) return operation.nl_explanation.text;
  const condition = operation.params.condition;
  if (["filter", "dropna", "drop_duplicates", "head", "tail"].includes(operation.kind)) {
    if (condition) return `“${condition}” 조건에 맞는 행을 남기고 나머지 행을 제외합니다.`;
    if (operation.kind === "dropna") return "결측값 제거 조건에 해당하는 행을 제외합니다.";
    if (operation.kind === "drop_duplicates") return "중복 제거 조건에 해당하는 행을 제외합니다.";
    return "이 코드의 선택 범위에 포함된 행만 남깁니다.";
  }
  if (target.kind === "removed") return column ? `변환 후에는 “${column}”의 이 데이터가 없어집니다. 삭제 전 값을 표에 남겨 표시합니다.` : "이 행은 변환 결과에서 제외됩니다. 삭제 전 값을 표에 남겨 표시합니다.";
  if (column && operation.params.formulas?.[column]) {
    const sources = operation.params.formulas[column].sources;
    return `${sources.length ? sources.map(c => `“${c}”`).join(", ") + " 값을 사용해 " : "코드의 계산식으로 "}“${column}” 값을 ${target.kind === "added" ? "만듭니다" : "변환합니다"}.`;
  }
  if (operation.kind === "aggregate") return `${operation.params.keys?.join(", ") || "그룹 기준"}별로 값을 집계해 결과를 만듭니다.`;
  if (operation.kind === "merge" || operation.kind === "join") return "코드에 지정된 연결 기준으로 입력 테이블을 합쳐 이 결과를 만듭니다.";
  if (operation.kind === "sort_values") return "코드에 지정된 열과 정렬 방향에 따라 행의 순서를 바꿉니다.";
  return target.kind === "added" ? "이 변환에서 새로 만들어진 데이터입니다." : "이 변환에서 입력 데이터의 값 또는 자료형이 바뀌었습니다.";
}

export function transformations(stage: Stage, target: ChangeTarget): Transformation[] {
  const operations = stage.operations?.filter(op => operationAffects(op, target)) || [];
  const nodes = operations.length ? operations : [stage];
  const seen = new Set<string>();
  return nodes.filter(node => { const key = `${node.code_location?.start}:${node.code}`; if (seen.has(key)) return false; seen.add(key); return true; }).map(node => ({
    code: node.code || node.operation_expression || stage.code,
    text: observedDescription(node, target), line: node.code_location || undefined,
  }));
}
