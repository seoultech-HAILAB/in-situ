import type { CellValue, Row, Stage, Table, OperationEffects } from "../../../src/types";

export type ChangeKind = "added" | "changed" | "removed";
export type DiffColumn = { name: string; kind?: ChangeKind };
export type DiffCell = { value: CellValue | undefined; before?: CellValue; after?: CellValue; kind?: ChangeKind };
export type DiffRow = { key: string; id: string; beforeId?: string; observation?: "before" | "after"; number: number; kind?: ChangeKind; cells: Record<string, DiffCell> };
export type WorkspaceDiff = { columns: DiffColumn[]; rows: DiffRow[]; before: Table | null; rowCorrespondenceKnown: boolean; removedRows: number; removedColumns: number };
export type ChangeTarget = { kind: ChangeKind; row?: DiffRow; column?: string; cell?: DiffCell; revision?: boolean };
export type Transformation = { id?: string; code: string; text: string; focus?: string; source?: string; outputColumns?: string[]; candidates?: boolean; mapping?: "candidate" | "matched"; line?: { start: number; end: number; start_column?: number; end_column?: number; start_character?: number } };

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
  const ids = new Set(stage.row_correspondence_complete ? Object.values(stage.row_correspondence || {}) : stage.table.rows.map(row => row.id));
  const score = (table: Table) => [table.rows.filter(row => ids.has(row.id)).length, table.columns.filter(c => stage.table.columns.includes(c)).length];
  return candidates.reduce<Table | null>((best, table) => {
    if (!best) return table;
    const a = score(table), b = score(best);
    return a[0] > b[0] || (a[0] === b[0] && a[1] > b[1]) ? table : best;
  }, null);
}

export function workspaceDiff(stage: Stage, comparison?: Table): WorkspaceDiff {
  const before = comparison ?? comparisonInput(stage), after = stage.table;
  if (!before) return { before, rowCorrespondenceKnown: false, columns: after.columns.map(name => ({ name })), rows: after.rows.map((row, i) => ({ key: row.id, id: row.id, number: i + 1, cells: Object.fromEntries(after.columns.map(c => [c, { value: row.values[c] }])) })), removedRows: 0, removedColumns: 0 };
  const oldRows = new Map(before.rows.map((row, i) => [row.id, { row, number: i + 1 }]));
  const oldColumns = new Set(before.columns), outputColumns = new Set(after.columns);
  const columns: DiffColumn[] = withDeleted(after.columns, before.columns, c => c).map(name => ({ name,
    kind: !outputColumns.has(name) ? "removed" : !oldColumns.has(name) ? "added" : undefined }));
  // Observation IDs in untraced Python are not correspondence. Never align
  // unrelated rows by their position, coincidentally equal IDs, or cell values.
  const preserving = new Set(["filter", "derive", "select", "drop", "rename", "sort_values", "astype", "fillna", "dropna", "drop_duplicates", "replace", "reset_index", "copy", "head", "tail"]);
  const members = stage.operations?.length ? stage.operations : [stage];
  const correspondence = comparison ? stage.revision_row_correspondence : stage.row_correspondence;
  const complete = comparison ? stage.revision_row_correspondence_complete : stage.row_correspondence_complete;
  const hasIdentity = !!complete || (stage.trace_level === "detailed" || stage.trace_level === "partial") && members.every(op => preserving.has(op.kind));
  const beforeId = (id: string) => complete ? correspondence?.[id] : hasIdentity ? id : undefined;
  const matched = (id: string) => oldRows.get(beforeId(id) ?? "");
  const outputIds = new Set(after.rows.map(row => beforeId(row.id)).filter((id): id is string => id !== undefined));
  const changedColumns = new Set<string>();
  for (const column of columns) if (!column.kind && before.stats.fields[column.name]?.dtype !== after.stats.fields[column.name]?.dtype) changedColumns.add(column.name);
  const retypedColumns = new Set(changedColumns);
  const oldOrder = before.columns.filter(c => outputColumns.has(c)), newOrder = after.columns.filter(c => oldColumns.has(c));
  newOrder.forEach((column, i) => { if (oldOrder[i] !== column) changedColumns.add(column); });
  const survivingBefore = before.rows.filter(row => outputIds.has(row.id));
  const survivingAfter = after.rows.filter(row => !!matched(row.id));
  const movedRows = new Set(hasIdentity ? survivingAfter.filter((row, i) => survivingBefore[i]?.id !== beforeId(row.id)).map(row => row.id) : []);
  const rows: DiffRow[] = after.rows.map((row, i) => {
    const old = matched(row.id)?.row;
    const cells: Record<string, DiffCell> = {};
    let changed = movedRows.has(row.id);
    for (const column of columns) {
      const c = column.name;
      if (column.kind === "removed") {
        cells[c] = old && owns(old, c) ? { value: old.values[c], before: old.values[c], kind: "removed" } : { value: undefined };
      } else if (column.kind === "added" || hasIdentity && !old) {
        cells[c] = { value: row.values[c], after: row.values[c], kind: "added" };
      } else if (!old) {
        cells[c] = { value: row.values[c], after: row.values[c] };
      } else {
        const inserted = !owns(old, c) && owns(row, c);
        const cleared = owns(old, c) && (!owns(row, c) || (old.values[c] != null && row.values[c] === null));
        const differs = !same(old.values[c], row.values[c]);
        const retyped = retypedColumns.has(c);
        cells[c] = { value: cleared ? old.values[c] : row.values[c], before: old.values[c], after: row.values[c], kind: cleared ? "removed" : inserted ? "added" : differs || retyped ? "changed" : undefined };
        if (differs || retyped) { changed = true; changedColumns.add(c); }
      }
    }
    return { key: `after:${row.id}`, id: row.id, beforeId: old ? beforeId(row.id) : undefined, observation: hasIdentity ? undefined : "after", number: i + 1, kind: hasIdentity && !old ? "added" : changed ? "changed" : undefined, cells };
  });
  for (const column of columns) if (!column.kind && changedColumns.has(column.name)) column.kind = "changed";
  const removedRows: DiffRow[] = before.rows.filter(row => !hasIdentity || !outputIds.has(row.id)).map(row => ({
    key: `before:${row.id}`, id: row.id, observation: hasIdentity ? undefined : "before", number: oldRows.get(row.id)!.number, kind: hasIdentity ? "removed" : undefined,
    cells: Object.fromEntries(columns.map(c => [c.name, owns(row, c.name) ? { value: row.values[c.name], before: row.values[c.name], kind: hasIdentity || c.kind === "removed" ? "removed" : undefined } : { value: undefined }])),
  }));
  const merged = hasIdentity ? withDeleted(rows, before.rows.map(row => removedRows.find(item => item.id === row.id) || rows.find(item => item.beforeId === row.id)!), row => row.beforeId ?? row.id) : [...rows, ...removedRows];
  return { before, rowCorrespondenceKnown: hasIdentity, columns, rows: merged, removedRows: hasIdentity ? removedRows.length : 0, removedColumns: columns.filter(c => c.kind === "removed").length };
}

function operationAffects(operation: Stage, target: ChangeTarget): boolean {
  if (!operation.input || ["python","setup"].includes(operation.kind)) return false;
  const diff = workspaceDiff(operation, operation.input);
  if (target.column && !target.row) return diff.columns.some(c => c.name === target.column && c.kind === target.kind);
  const preserving = new Set(["filter", "derive", "select", "drop", "rename", "sort_values", "astype", "fillna", "dropna", "drop_duplicates", "replace", "reset_index", "copy", "head", "tail"]);
  const identity = ["detailed","partial"].includes(operation.trace_level || "") && preserving.has(operation.kind);
  if (!identity) {
    if (!target.column || !target.row) return false;
    const schema = diff.columns.find(c => c.name === target.column)?.kind;
    if (schema !== target.kind || !["added","removed"].includes(schema || "")) return false;
    const table = schema === "added" ? operation.table : operation.input;
    return table.rows.some(row => row.id === target.row!.id);
  }
  const row = diff.rows.find(row => row.id === target.row?.id && (target.column || row.kind === target.kind));
  return !!row && (target.column ? row.cells[target.column]?.kind === target.kind : row.kind === target.kind);
}

function matchesEffects(effects: OperationEffects, target: ChangeTarget) {
  if (target.row?.observation && target.column && ["added","removed"].includes(target.kind)) return effects.columns[target.kind].includes(target.column);
  if (target.column && target.row) return effects.cells[target.kind][target.column]?.includes(target.row.id) ?? false;
  if (target.column) return effects.columns[target.kind].includes(target.column);
  return !!target.row && effects.rows[target.kind].includes(target.row.id);
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

export function availableTransformations(stage: Stage) {
  const items = (stage.transformations || []).filter(item => item.contributes_to_output !== false && (!item.execution_version || item.execution_version === stage.execution_version) && (!item.code_version || item.code_version === stage.code_version));
  // Keep unresolved AST operations available. For the same actual statement,
  // both conditions display the shared observed-change explanation once.
  const linked = items.filter(item => item.method === "observed_change");
  return [...linked, ...items.filter(item => item.method !== "observed_change" && !linked.some(other =>
    other.code === item.code || other.code_location.start === item.code_location.start && other.output_columns.some(c => item.output_columns.includes(c))
  ))];
}

export function transformationDetails(item: NonNullable<Stage["transformations"]>[number]): Transformation {
  return { id: item.id, code: item.code, text: item.description.text, source: item.description.source,
    focus: item.focus_code, line: item.code_location, outputColumns: item.output_columns, mapping: item.mapping_status };
}

export function transformations(stage: Stage, target: ChangeTarget): Transformation[] {
  if (stage.transformations) {
    let matched = (stage.transformations || []).filter(item => item.contributes_to_output !== false && (!item.execution_version || item.execution_version === stage.execution_version) && (!item.code_version || item.code_version === stage.code_version)).filter(item =>
      (target.revision ? item.revision_effects : item.execution_effects)?.some(effect => matchesEffects(effect,target))
    );
    const linked = matched.filter(item => item.method === "observed_change");
    if (linked.length) matched = linked;
    const assignments=matched.filter(item=>item.method==='assignment');
    return matched.filter(item=>item.method==='assignment' || !assignments.some(assignment=>
      assignment.statement_index===item.statement_index && ['derive','convert'].includes(item.kind) && assignment.output_columns.some(column=>item.output_columns.includes(column))
    )).map(item => ({...transformationDetails(item),candidates:(target.revision ? item.revision_effects : item.execution_effects)?.some(effect=>matchesEffects(effect,target)&&['step-search-candidate','llm-step-candidate'].includes(effect.attribution || ''))}));
  }
  // Legacy records can still match an actual operation, but never the whole Step.
  if (target.revision) return [];
  const nodes = stage.operations?.filter(op => (!op.execution_version || op.execution_version === stage.execution_version) && (!op.code_version || op.code_version === stage.code_version) && operationAffects(op, target)) || [];
  const seen = new Set<string>();
  return nodes.filter(node => { const key = `${node.expression_location?.start ?? node.code_location?.start}:${node.expression_location?.start_column ?? 0}:${node.operation_expression || node.code}`; if (seen.has(key)) return false; seen.add(key); return true; }).map(node => ({
    code: node.operation_expression || node.code,
    text: observedDescription(node, target), line: node.expression_location || node.code_location || undefined,
  }));
}
