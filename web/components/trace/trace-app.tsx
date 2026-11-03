"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  api,
  combineSelection,
  isExplained,
  researchView,
  reviewRun,
  selectedCells,
  type Condition,
  type Health,
  type ReviewTarget,
  type Run,
  type Selection,
  type Session,
  type Stage,
  type TaskInput,
  type TaskSummary,
} from "@/lib/trace";
import { Review } from "./review";
import { TaskStart } from "./task-start";
import { describeTarget } from "./target-text";
import type { Scope } from "./scope-select";

const SESSION_KEY = "trace-woz-session";
// Same minimum wait in both conditions so preparation time never differs.
const MIN_PREPARE_MS = 1200;

export type Comment = {
  target: ReviewTarget;
  anchor: HTMLElement;
  baseRunId: string;
  title: string;
  preview: string;
  scope: Scope;
  error: string;
  editing: boolean;
};

export function TraceApp() {
  const research = useMemo(researchView, []);
  const [health, setHealth] = useState<Health | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [entry, setEntry] = useState(false);
  const [booting, setBooting] = useState(true);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [task, setTask] = useState<TaskInput | null>(null);
  const [condition, setCondition] = useState<Condition>("in-situ");
  const [preparing, setPreparing] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [stepId, setStepId] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [picked, setPicked] = useState<ReviewTarget | null>(null);
  const pickedRef = useRef<ReviewTarget | null>(null);
  const [comment, setComment] = useState<Comment | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [request, setRequest] = useState("");
  const [scope, setScope] = useState<Scope>("step");

  const run = useMemo(() => reviewRun(session?.run), [session?.run]);
  const steps = useMemo(() => run?.stages.filter((s) => s.kind !== "input") ?? [], [run]);
  const step = steps.find((s) => s.id === stepId) ?? steps[0];
  const isEx = session?.condition === "ex";

  const clearPick = useCallback(() => {
    pickedRef.current = null;
    setPicked(null);
    setSelection(null);
    setComment(null);
  }, []);
  useEffect(clearPick, [clearPick, session?.id, run?.id, step?.id, session?.condition]);

  const log = useCallback(
    async (event: string, data: Record<string, unknown> = {}) => {
      if (!session) return;
      try {
        await api(`/sessions/${session.id}/events`, {
          event,
          data,
          execution_version: session.run?.id,
          condition: session.condition,
        });
      } catch {
        setError("행동 기록을 저장하지 못했습니다. 네트워크 연결을 확인하세요.");
      }
    },
    [session],
  );

  function accept(next: Session) {
    setSession(next);
    setCondition(next.condition);
    setEntry(false);
    localStorage.setItem(SESSION_KEY, next.id);
    const url = new URL(location.href);
    url.searchParams.set("session", next.id);
    history.replaceState(null, "", url);
    const nextSteps = reviewRun(next.run)?.stages.filter((s) => s.kind !== "input") ?? [];
    if (!nextSteps.some((s) => s.id === stepId)) setStepId(nextSteps[0]?.id ?? "");
  }

  async function perform(label: string, work: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  // Boot: health, task list, and any session in the URL or this browser.
  useEffect(() => {
    api<Health>("/health")
      .then(async (h) => {
        setHealth(h);
        const sid = new URLSearchParams(location.search).get("session") || localStorage.getItem(SESSION_KEY);
        if (!sid) return setEntry(true);
        try {
          accept(await api<Session>(`/sessions/${sid}`));
        } catch {
          localStorage.removeItem(SESSION_KEY);
          const url = new URL(location.href);
          url.searchParams.delete("session");
          history.replaceState(null, "", url);
          setEntry(true);
        }
      })
      .catch(() => setError("서버에 연결할 수 없습니다. FastAPI 서버가 실행 중인지 확인하세요."))
      .finally(() => setBooting(false));
    api<TaskSummary[]>("/woz-tasks")
      .then(setTasks)
      .catch((e) => setError((e as Error).message))
      .finally(() => setTasksLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!run || !session || entry || !isExplained(run)) return;
    void log("review_started", {
      presentation_version: "two-condition-next-v1",
      revision_interface: isEx ? "panel-v1" : "selection-action-v3",
      condition_variant: session.condition_variant,
      workspace: isEx ? "code-and-result" : "before-and-after",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, session?.condition, run?.explanation_status, entry]);

  const chooseTask = (id: string) =>
    perform("과제 표를 불러오는 중", async () => {
      setTask(null);
      setTask({ ...(await api<TaskInput>(`/woz-tasks/${id}/input`)), id });
    });

  const start = () =>
    perform("검수 화면을 준비하는 중", async () => {
      if (!task) return;
      setPreparing(true);
      const began = performance.now();
      try {
        const next = await api<Session>(`/woz-tasks/${task.id}/start`, {
          input_csv: task.input_csv,
          target_csv: task.target_csv,
          condition,
        });
        const wait = MIN_PREPARE_MS - (performance.now() - began);
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
        setRequest("");
        setScope("step");
        accept(next);
      } finally {
        setPreparing(false);
      }
    });

  function selectStep(id: string) {
    if (id === step?.id) return;
    setStepId(id);
    void log("step_selected", { step_id: id, navigation: "explicit-workflow" });
  }

  function openComment(stage: Stage, target: ReviewTarget, anchor: HTMLElement, final = true, additive = false, editing = false) {
    if (isEx || busy || !run || !session) return null;
    const data = stage.table;
    if (additive) {
      const combined = combineSelection(pickedRef.current, target, data);
      if (!combined) {
        clearPick();
        return null;
      }
      target = combined;
    }
    pickedRef.current = target;
    setPicked(target);
    if (target.kind !== "cell") setSelection(null);
    const text = describeTarget(target, data);
    setComment({ target, anchor, baseRunId: run.id, title: text.title, preview: text.preview, scope, error: "", editing: editing && final });
    if (final) {
      void log("review_target_selected", { target, interaction: "selection-action-v3" });
      if (target.kind === "row") void log("row_selected", { step_id: stage.id, row_id: target.row_id, removed: false });
      if (target.kind === "column") void log("column_selected", { step_id: stage.id, column: target.column, removed: false });
    }
    return target;
  }

  function selectCell(stage: Stage, row: string, column: string, anchor: HTMLElement, role: "input" | "output", inputRef: string | undefined, additive: boolean) {
    const target = openComment(
      stage,
      { kind: "cell", step_id: stage.id, operation_id: stage.view_operation_id, row_id: row, column, table_role: role, ...(inputRef ? { input_ref: inputRef } : {}) },
      anchor,
      true,
      additive,
    );
    if (!target) return;
    const points = selectedCells(target, stage.table);
    setSelection(
      points.length === 1
        ? { step: stage.id, operation_id: stage.view_operation_id, row: points[0].row_id, column: points[0].column, table_role: role, ...(inputRef ? { input_ref: inputRef } : {}) }
        : null,
    );
    void log("cell_selected", { step_id: stage.id, row_id: row, column, table_role: role, input_ref: inputRef, selects: "cell" });
    void log("lineage_viewed", { step_id: stage.id, row_id: row, column, table_role: role, input_ref: inputRef });
  }

  const draftKey = (c: Comment) => JSON.stringify([session?.id, c.baseRunId, c.target]);

  async function generate(body: Record<string, unknown>) {
    if (!session) return false;
    const next = await api<Session>(`/sessions/${session.id}/generate`, body);
    accept(next);
    if (next.status === "ready" && next.run) {
      toast.success("수정을 반영해 다시 실행했습니다");
      return true;
    }
    throw new Error(next.error?.message || "수정을 적용하지 못했습니다. 이전 결과를 그대로 표시합니다.");
  }

  async function submitComment() {
    if (!comment || !run || busy) return;
    const submitted = comment;
    const text = (drafts[draftKey(submitted)] || "").trim();
    if (!text) return;
    if (submitted.baseRunId !== run.id) {
      setComment({ ...submitted, error: "결과가 바뀌었습니다. 표에서 다시 선택하세요." });
      return;
    }
    setBusy("수정을 반영해 다시 실행하는 중");
    setComment({ ...submitted, error: "" });
    try {
      await generate({
        request: text,
        scope: submitted.scope,
        base_run_id: submitted.baseRunId,
        context: { step_id: submitted.target.step_id, review_target: submitted.target, interaction: "selection-action-v3" },
      });
      setDrafts((d) => ({ ...d, [draftKey(submitted)]: "" }));
      clearPick();
    } catch (e) {
      setComment({ ...submitted, error: (e as Error).message });
    } finally {
      setBusy("");
    }
  }

  const revise = () =>
    perform("수정을 반영해 다시 실행하는 중", async () => {
      if (!session || !step) return;
      await generate({ request, scope, base_run_id: session.run?.id, context: { step_id: step.id, selection: null } });
      setRequest("");
    });

  const mutate = (path: "undo" | "confirm") =>
    perform(path === "undo" ? "이전 결과로 되돌리는 중" : "결과를 확정하는 중", async () => {
      if (!session) return;
      accept(await api<Session>(`/sessions/${session.id}/${path}`, {}));
      toast.success(path === "undo" ? "이전 결과로 되돌렸습니다" : "결과를 확정했습니다");
    });

  const switchCondition = (next: Condition) =>
    perform("조건을 바꾸는 중", async () => {
      if (!session) return;
      clearPick();
      accept(await api<Session>(`/sessions/${session.id}/condition`, { condition: next }));
    });

  const reloadExplanations = () =>
    perform("단계 설명을 불러오는 중", async () => {
      if (!session || !run) return;
      accept(await api<Session>(`/sessions/${session.id}/explanations`, { run_id: run.id }));
    });

  if (booting) return <Centered label="불러오는 중" />;
  if (preparing) return <Centered label="검수 화면을 준비하는 중" />;

  const errorBanner = error && (
    <Alert variant="destructive" className="mx-auto mt-4 w-[calc(100%-3rem)] max-w-6xl">
      <AlertTitle>요청을 처리하지 못했습니다</AlertTitle>
      <AlertDescription>{error}</AlertDescription>
    </Alert>
  );

  if (entry || !session) {
    return (
      <>
        {errorBanner}
        {health && !health.api_configured && (
          <Alert className="mx-auto mt-4 w-[calc(100%-3rem)] max-w-6xl">
            <AlertTitle>OPENAI_API_KEY가 설정되지 않았습니다</AlertTitle>
            <AlertDescription>저장된 과제는 열 수 있지만 수정 요청은 처리되지 않습니다. .env에 키를 넣고 서버를 다시 시작하세요.</AlertDescription>
          </Alert>
        )}
        <TaskStart
          tasks={tasks}
          loading={tasksLoading}
          task={task}
          condition={condition}
          busy={!!busy}
          onTask={chooseTask}
          onCondition={setCondition}
          onStart={start}
          onResume={session ? () => setEntry(false) : undefined}
        />
      </>
    );
  }

  return (
    <Review
      session={session}
      run={run as Run | undefined}
      steps={steps}
      step={step}
      research={research}
      busy={busy}
      errorBanner={errorBanner}
      selection={selection}
      picked={picked}
      comment={comment}
      commentText={comment ? drafts[draftKey(comment)] || "" : ""}
      request={request}
      scope={scope}
      onRequest={setRequest}
      onScope={setScope}
      onStep={selectStep}
      onRevise={revise}
      onUndo={() => mutate("undo")}
      onConfirm={() => mutate("confirm")}
      onCondition={switchCondition}
      onNewTask={() => {
        clearPick();
        setEntry(true);
      }}
      onReloadExplanations={reloadExplanations}
      onCell={selectCell}
      onTarget={openComment}
      onCommentEdit={() => {
        if (!comment) return;
        setComment({ ...comment, editing: true });
        void log("review_comment_opened", { target: comment.target, interaction: "selection-action-v3" });
      }}
      onCommentText={(text) => comment && setDrafts((d) => ({ ...d, [draftKey(comment)]: text }))}
      onCommentScope={(value) => {
        setScope(value);
        setComment((c) => (c ? { ...c, scope: value } : c));
      }}
      onCommentClose={clearPick}
      onCommentSubmit={() => void submitComment()}
    />
  );
}

function Centered({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="flex min-h-dvh items-center justify-center gap-3 text-muted-foreground">
      <LoaderCircle className="size-5 animate-spin" />
      {label}
    </div>
  );
}
