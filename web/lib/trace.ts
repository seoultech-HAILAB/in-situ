// Shared review logic lives in ../src so the existing node tests keep covering it.
export type * from "../../src/types";
export { cellKey, stepTitle, tableChanges, type TableChanges } from "../../src/tableChanges";
export { selectedCells, pointKey, combineSelection } from "../../src/tableSelection";
export { reviewGroups, groupColor, groupBorder } from "../../src/reviewGroups";
export { reviewRun, workflowInputs, referencedOutputs, buildWorkflowGraph, ownerOf } from "../../src/workflowGraph";
export { useTableDrag } from "../../src/useTableDrag";
export { PythonCode, sourceSnippet } from "../components/trace/python-code";

import type { CellValue, Run, Session, Stage, Table } from "../../src/types";

export type TaskSummary = { id: string; title: string; review_number?: number | null };
export type TaskInput = TaskSummary & {
  input_csv: string;
  target_csv: string;
  input: Table;
  target: Table;
  sources: Record<string, Table>;
};
export type Health = { api_configured: boolean; model: string; access_role: string; pilot_account: boolean };

export const researchView = () =>
  typeof window !== "undefined" && new URLSearchParams(window.location.search).get("research") === "1";

const explanationsReady = (run: Run) =>
  run.explanation_status === "ready" &&
  run.stages
    .slice(1)
    .every(
      (stage) =>
        stage.transformations_version === "ast-transformations-v1" &&
        (stage.transformations || []).every(item => !!item.description?.text) &&
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
export async function api<T>(path: string, body?: unknown, options = { explain: true }): Promise<T> {
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
  if (options.explain && !path.endsWith("/explanations") && isSession && !explanationsReady(data.run)) {
    try {
      const described = await fetch(`/api/sessions/${data.id}/explanations`, {
        method: "POST",
        headers,
        body: JSON.stringify({ run_id: data.run.id, refresh_transformations: path.endsWith("/generate") || path.endsWith("/preview/apply") }),
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

export type { Session };
