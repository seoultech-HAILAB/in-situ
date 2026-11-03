// Shared review logic lives in ../src so the existing node tests keep covering it.
export type * from "../../src/types";
export { cellKey, stepTitle, tableChanges, type TableChanges } from "../../src/tableChanges";
export { selectedCells, pointKey, combineSelection } from "../../src/tableSelection";
export { reviewGroups, groupColor, groupBorder } from "../../src/reviewGroups";
export { reviewRun, workflowInputs, referencedOutputs, buildWorkflowGraph, ownerOf } from "../../src/workflowGraph";
export { useTableDrag } from "../../src/useTableDrag";
export { PythonCode } from "../../src/PythonCode";

import type { CellValue, Condition, ReviewTarget, Run, Session as BaseSession, Stage, Table } from "../../src/types";

/** One review-history record: what the participant opened, noted, or marked, per execution version. */
export type HistoryEvent = "explanation_viewed" | "evidence_viewed" | "code_viewed" | "review_note_saved" | "review_mark_set";
export type HistoryEntry = {
  id?: string;
  timestamp?: string;
  event: HistoryEvent;
  execution_version: string | null;
  data: { target: ReviewTarget; note?: string; checked?: boolean };
};
export const HISTORY_EVENTS: HistoryEvent[] = ["explanation_viewed", "evidence_viewed", "code_viewed", "review_note_saved", "review_mark_set"];
/** A revision candidate that has run but is not yet the current result. */
export type Preview = { run: Run; request: string; scope: "step" | "pipeline"; context?: { step_id?: string } | null; base_run_id: string };
export type Session = BaseSession & { review_history?: HistoryEntry[]; events?: HistoryEntry[]; preview?: Preview; participant_label?: string };

/** Stable identity of a review target, used to attach history to it. */
export const targetKey = (t: ReviewTarget) =>
  JSON.stringify([t.step_id, t.table_role || "output", t.input_ref || "", t.operation_id || "", t.kind, t.row_id || "", t.column || "", t.row_ids || [], t.columns || [], t.cells || []]);

export type TaskSummary = { id: string; title: string; review_number?: number | null };
export type TaskInput = TaskSummary & {
  input_csv: string;
  target_csv: string;
  input: Table;
  target: Table;
  sources: Record<string, Table>;
};
export type SessionRow = {
  session_id: string;
  task_id: string;
  title: string;
  condition: Condition;
  participant_label?: string | null;
  started_at: string;
  status: string;
  confirmed: boolean;
  revision_requests: number;
  revision_executions: number;
  undo_count: number;
  event_count: number;
  last_event?: string | null;
  last_event_at?: string | null;
  preview_pending?: boolean;
};
export type LogEvent = { id: string; timestamp: string; event: string; execution_version?: string | null; data?: Record<string, unknown> };
export type Health = { api_configured: boolean; model: string; access_role: string; pilot_account: boolean };

export const researchView = () =>
  typeof window !== "undefined" && new URLSearchParams(window.location.search).get("research") === "1";

const explanationsReady = (run: Run) =>
  run.explanation_status === "ready" &&
  run.stages
    .slice(1)
    .every(
      (stage) =>
        stage.column_explanations !== undefined &&
        (stage.operations || []).every((op) => op.column_explanations !== undefined),
    );

async function readError(res: Response) {
  try {
    const data = await res.json();
    return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
  } catch {
    return `서버 오류 (${res.status})`;
  }
}

// Same contract as the legacy client: session responses whose explanations are
// missing trigger one explanation request so both conditions see identical text.
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const headers = {
    "Content-Type": "application/json",
    "X-Trace-View": researchView() ? "researcher" : "participant",
  };
  const res = await fetch(
    "/api" + path,
    body === undefined ? { headers } : { method: "POST", headers, body: JSON.stringify(body) },
  );
  if (!res.ok) throw new Error(await readError(res));
  let data = await res.json();
  const isSession =
    data?.run && Array.isArray(data.runs) && ["ex", "in-situ"].includes(data.condition);
  if (!path.endsWith("/explanations") && isSession && !explanationsReady(data.run)) {
    try {
      const described = await fetch(`/api/sessions/${data.id}/explanations`, {
        method: "POST",
        headers,
        body: JSON.stringify({ run_id: data.run.id }),
      });
      if (described.ok) data = await described.json();
      else if (described.status === 409) {
        const latest = await fetch(`/api/sessions/${data.id}`, { headers });
        if (latest.ok) data = await latest.json();
      } else {
        data.run.explanation_status = "failed";
        data.run.explanation_error = "단계 설명을 불러오지 못했습니다.";
      }
    } catch {
      data.run.explanation_status = "failed";
      data.run.explanation_error = "설명 서버에 연결하지 못했습니다.";
    }
  }
  return data;
}

export const isExplained = (run: Run) => explanationsReady(run);

export function fmt(v: CellValue | undefined): string {
  if (v == null) return "";
  if (Array.isArray(v)) return JSON.stringify(v);
  if (typeof v === "number")
    return v !== 0 && Math.abs(v) < 0.000001 ? String(v) : v.toLocaleString("ko-KR", { maximumFractionDigits: 20 });
  return String(v);
}

export const stepName = (stage: Stage, fallback: (s: Stage) => string) =>
  stage.nl_explanation?.title || fallback(stage);

export const taskLabel = (task: TaskSummary) =>
  typeof task.review_number === "number" ? `과제 ${task.review_number}. ${task.title}` : task.title;

