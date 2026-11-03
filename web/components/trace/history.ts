import { HISTORY_EVENTS, pointKey, selectedCells, targetKey, type HistoryEntry, type ReviewTarget, type Session, type Table } from "@/lib/trace";

export type TargetRecord = {
  target: ReviewTarget;
  viewed: Set<"explanation_viewed" | "evidence_viewed" | "code_viewed">;
  note: string;
  checked: boolean;
};

/** Server history (own events only) plus records logged since the last session response. */
export function sessionHistory(session: Session, local: HistoryEntry[]): HistoryEntry[] {
  const server = session.review_history ?? (session.events || []).filter((e) => HISTORY_EVENTS.includes(e.event));
  const known = new Set(server.map((e) => e.id).filter(Boolean));
  return [...server, ...local.filter((e) => !e.id || !known.has(e.id))];
}

/**
 * Fold one execution version's events into per-target records. Records from other
 * versions are never carried over: a new run needs its own review.
 */
export function recordsFor(history: HistoryEntry[], runId: string | undefined): Map<string, TargetRecord> {
  const out = new Map<string, TargetRecord>();
  for (const e of history) {
    if (!runId || e.execution_version !== runId || !e.data?.target) continue;
    const key = targetKey(e.data.target);
    const rec = out.get(key) || { target: e.data.target, viewed: new Set(), note: "", checked: false };
    if (e.event === "review_note_saved") rec.note = e.data.note || "";
    else if (e.event === "review_mark_set") rec.checked = !!e.data.checked;
    else rec.viewed.add(e.event);
    out.set(key, rec);
  }
  return out;
}

export const hasActivity = (r: TargetRecord) => r.viewed.size > 0 || !!r.note || r.checked;

export const VIEW_LABEL = { explanation_viewed: "규칙", evidence_viewed: "입력 근거", code_viewed: "코드" } as const;

export type Mark = "viewed" | "checked";
export type Marks = Map<string, Mark>;

/** Margin marks for one table: `col:`, `row:` and `cell:` keys, checked wins over viewed. */
export function tableMarks(
  records: Map<string, TargetRecord>,
  where: { step: string; role: "input" | "output"; inputRef?: string; operation?: string },
  data: Table,
): Marks {
  const out: Marks = new Map();
  const put = (key: string, mark: Mark) => out.get(key) !== "checked" && out.set(key, mark);
  for (const rec of records.values()) {
    const t = rec.target;
    if (!hasActivity(rec) || t.step_id !== where.step || (t.table_role || "output") !== where.role || t.input_ref !== where.inputRef || t.operation_id !== where.operation) continue;
    const mark: Mark = rec.checked ? "checked" : "viewed";
    if (t.kind === "column" && t.column) put(`col:${t.column}`, mark);
    else if (t.kind === "columns") t.columns?.forEach((c) => put(`col:${c}`, mark));
    else if (t.kind === "row" && t.row_id) put(`row:${t.row_id}`, mark);
    else if (t.kind !== "step") selectedCells(t, data).forEach((c) => put(`cell:${pointKey(c.row_id, c.column)}`, mark));
  }
  return out;
}
