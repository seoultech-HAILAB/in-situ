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
  type HistoryEntry,
  type HistoryEvent,
  type ReviewTarget,
  type Run,
  type Selection,
  type Session,
  type Stage,
  type TaskInput,
  type TaskSummary,
} from "@/lib/trace";
import { sessionHistory } from "./history";
import { Review, type Pick } from "./review";
import { TaskStart } from "./task-start";
import type { Scope } from "./scope-select";

/** Participant link from the admin page: `/?task=ID&condition=in-situ&pid=P01`. */
type Link = { task: string; condition: Condition; pid: string };
function readLink(): Link | null {
  const q = new URLSearchParams(location.search);
  const task = q.get("task");
  const condition = q.get("condition");
  if (!task || (condition !== "ex" && condition !== "in-situ")) return null;
  return { task, condition, pid: q.get("pid") || "" };
}
const linkKey = (l: Link) => `trace-link:${l.task}:${l.condition}:${l.pid}`;
// Same minimum wait in both conditions so preparation time never differs.
const MIN_PREPARE_MS = 1200;

export function TraceApp() {
  const research = useMemo(researchView, []);
  const [link, setLink] = useState<Link | null>(null);
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
  const [pick, setPick] = useState<Pick | null>(null);
  const pickRef = useRef<Pick | null>(null);
  const [localHistory, setLocalHistory] = useState<HistoryEntry[]>([]);
  const [request, setRequest] = useState("");
  const [scope, setScope] = useState<Scope>("step");

  const run = useMemo(() => reviewRun(session?.run), [session?.run]);
  const steps = useMemo(() => run?.stages.filter((s) => s.kind !== "input") ?? [], [run]);
  const step = steps.find((s) => s.id === stepId) ?? steps[0];
  const isEx = session?.condition === "ex";

  const clearPick = useCallback(() => {
    pickRef.current = null;
    setPick(null);
    setSelection(null);
  }, []);
  useEffect(clearPick, [clearPick, session?.id, run?.id, session?.condition]);
  const reviewHistory = useMemo(() => (session ? sessionHistory(session, localHistory) : []), [session, localHistory]);

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
    setLocalHistory([]);
    setCondition(next.condition);
    setEntry(false);
    const l = readLink();
    if (l) localStorage.setItem(linkKey(l), next.id);
    else {
      const url = new URL(location.href);
      url.searchParams.set("session", next.id);
      history.replaceState(null, "", url);
    }
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

  // Boot: a participant link resumes only its own session; `?session=` opens one directly.
  useEffect(() => {
    const l = readLink();
    setLink(l);
    api<Health>("/health")
      .then(async (h) => {
        setHealth(h);
        const sid = new URLSearchParams(location.search).get("session") || (l && localStorage.getItem(linkKey(l)));
        const fresh = () => {
          setEntry(true);
          if (l) {
            setCondition(l.condition);
            void chooseTask(l.task);
          }
        };
        if (!sid) return fresh();
        try {
          const found = await api<Session>(`/sessions/${sid}`);
          if (l && (found.task_id !== l.task || found.condition !== l.condition)) throw new Error("other task");
          accept(found);
        } catch {
          if (l) localStorage.removeItem(linkKey(l));
          fresh();
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
      presentation_version: "two-condition-next-v2",
      revision_interface: isEx ? "composer-v1" : "inspector-composer-v1",
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
          condition: link?.condition ?? condition,
          ...(link?.pid ? { participant: link.pid } : {}),
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
    clearPick();
    setStepId(id);
    void log("step_selected", { step_id: id, navigation: "explicit-workflow" });
  }

  function openTarget(stage: Stage, target: ReviewTarget, final = true, additive = false) {
    if (isEx || busy || !run || !session) return null;
    if (additive) {
      const prev = pickRef.current?.stage.table === stage.table ? pickRef.current.target : null;
      const combined = combineSelection(prev, target, stage.table);
      if (!combined) {
        clearPick();
        return null;
      }
      target = combined;
    }
    const next = { target, stage };
    pickRef.current = next;
    setPick(next);
    if (target.kind !== "cell") setSelection(null);
    if (final) {
      void log("review_target_selected", { target, interaction: "inspector-v1" });
      if (target.kind === "row") void log("row_selected", { step_id: stage.id, row_id: target.row_id, removed: false });
      if (target.kind === "column") void log("column_selected", { step_id: stage.id, column: target.column, removed: false });
    }
    return target;
  }

  function selectCell(stage: Stage, row: string, column: string, role: "input" | "output", inputRef: string | undefined, additive: boolean) {
    const target = openTarget(
      stage,
      { kind: "cell", step_id: stage.id, operation_id: stage.view_operation_id, row_id: row, column, table_role: role, ...(inputRef ? { input_ref: inputRef } : {}) },
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

  /** Review history is logged per execution version and shown back immediately. */
  function recordHistory(event: HistoryEvent, target: ReviewTarget, extra: Record<string, unknown> = {}) {
    if (!session?.run) return;
    const data = { target, ...extra };
    setLocalHistory((h) => [...h, { event, execution_version: session.run!.id, data }]);
    void log(event, data);
  }

  // Every request first runs as a preview; the participant applies or discards it.
  const submit = () =>
    perform("수정 결과를 미리 만드는 중", async () => {
      if (!session?.run || !step || !request.trim()) return;
      const target = pick?.target ?? { kind: "step" as const, step_id: step.id };
      const context = isEx
        ? { step_id: step.id, selection: null, interaction: "composer-v1" }
        : { step_id: target.step_id, review_target: target, interaction: "inspector-composer-v1" };
      const next = await api<Session>(`/sessions/${session.id}/generate`, { request, scope, base_run_id: session.run.id, context, preview: true });
      accept(next);
      if (!next.preview) throw new Error(next.error?.message || "수정을 적용하지 못했습니다. 이전 결과를 그대로 표시합니다.");
    });

  const decidePreview = (decision: "apply" | "discard") =>
    perform(decision === "apply" ? "수정을 적용하는 중" : "미리보기를 닫는 중", async () => {
      if (!session?.preview) return;
      accept(await api<Session>(`/sessions/${session.id}/preview/${decision}`, { run_id: session.preview.run.id }));
      if (decision === "apply") {
        setRequest("");
        clearPick();
        toast.success("수정을 적용했습니다");
      }
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
        {!link && !research ? (
          <main className="flex min-h-dvh items-center justify-center px-6 text-center text-muted-foreground">연구자에게 받은 링크로 접속하세요.</main>
        ) : (
        <TaskStart
          fixed={!!link}
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
        )}
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
      error={error}
      selection={selection}
      pick={pick}
      history={reviewHistory}
      request={request}
      scope={scope}
      onRequest={setRequest}
      onScope={setScope}
      onStep={selectStep}
      onSubmit={submit}
      onApplyPreview={() => decidePreview("apply")}
      onDiscardPreview={() => decidePreview("discard")}
      onUndo={() => mutate("undo")}
      onConfirm={() => mutate("confirm")}
      onCondition={switchCondition}
      onNewTask={() => {
        clearPick();
        setEntry(true);
      }}
      onReloadExplanations={reloadExplanations}
      onCell={selectCell}
      onTarget={openTarget}
      onClearPick={clearPick}
      onHistory={recordHistory}
      onAsk={(target) => void log("review_comment_opened", { target, interaction: "inspector-composer-v1" })}
      onSummaryOpen={() => void log("review_summary_opened", {})}
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
