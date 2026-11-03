"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { ArrowUp, Check, ChevronLeft, ChevronRight, Download, LoaderCircle, Play, RotateCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api as traceApi, PythonCode, taskLabel, type Health, type Session, type TaskInput, type TaskSummary } from "@/lib/trace";
import { WorkspaceTable } from "./workspace-table";

const SESSION_KEY = "trace-woz-session";
const api = <T,>(path: string, body?: unknown) => traceApi<T>(path, body, { explain: false });
type Scope = "step" | "pipeline";
type Message = { id: string; request: string; response: string; failed?: boolean };
type PanelSizes = { code: number; chat: number; top: number };
const DEFAULT_SIZES: PanelSizes = { code: 50, chat: 25, top: 73 };

export function TraceApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [taskId, setTaskId] = useState("");
  const [stepId, setStepId] = useState("");
  const [request, setRequest] = useState("");
  const [scope, setScope] = useState<Scope>("step");
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<Message | null>(null);
  const [failures, setFailures] = useState<Message[]>([]);
  const [sizes, setSizes] = useState<PanelSizes>(DEFAULT_SIZES);
  const [tableView, setTableView] = useState("output");
  const root = useRef<HTMLDivElement>(null);
  const codeList = useRef<HTMLDivElement>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const inFlight = useRef(false);
  const run = session?.run;
  // Code blocks and tables use the same actual execution stage.
  const steps = useMemo(() => run?.stages.filter((stage) => stage.kind !== "input") ?? [], [run]);
  const step = steps.find((stage) => stage.id === stepId) ?? steps[0];
  const stepIndex = steps.findIndex((stage) => stage.id === step?.id);
  const taskChanged = !!session && taskId !== session.task_id;

  function accept(next: Session) {
    setSession(next);
    setTaskId(next.task_id);
    localStorage.setItem(SESSION_KEY, next.id);
    const url = new URL(location.href);
    url.searchParams.set("session", next.id);
    history.replaceState(null, "", url);
  }

  useEffect(() => {
    let active = true;
    try {
      const stored = JSON.parse(localStorage.getItem("workspace-panels") || "null");
      if (stored && ["code", "chat", "top"].every((key) => Number.isFinite(stored[key]))) {
        setSizes({ code: Math.min(75, Math.max(25, stored.code)), chat: Math.min(45, Math.max(20, stored.chat)), top: Math.min(85, Math.max(40, stored.top)) });
      }
    } catch { /* Ignore malformed local preferences. */ }
    void Promise.all([api<Health>("/health"), api<TaskSummary[]>("/woz-tasks")])
      .then(async ([nextHealth, nextTasks]) => {
        if (!active) return;
        setHealth(nextHealth);
        setTasks(nextTasks);
        setTaskId(nextTasks[0]?.id ?? "");
        const sid = new URLSearchParams(location.search).get("session") || localStorage.getItem(SESSION_KEY);
        if (!sid) return;
        try {
          const restored = await api<Session>(`/sessions/${encodeURIComponent(sid)}`);
          if (active) accept(restored);
        } catch {
          if (!active) return;
          localStorage.removeItem(SESSION_KEY);
          const url = new URL(location.href);
          url.searchParams.delete("session");
          history.replaceState(null, "", url);
          setError("이전 작업을 불러오지 못했습니다. 과제를 선택해 다시 실행하세요.");
        }
      })
      .catch((e: Error) => active && setError(e.message))
      .finally(() => active && setBooting(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    codeList.current?.querySelector<HTMLElement>("[data-selected=true]")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [step?.id, run?.id]);
  useEffect(() => { setTableView("output"); }, [step?.id, run?.id]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [pending, failures, run?.id]);

  // Follow ancestry so undo and forks show only the current execution's history.
  const messages = useMemo(() => {
    const history: Message[] = [];
    const runs = new Map(session?.runs.map((item) => [item.id, item]));
    let current = run;
    const seen = new Set<string>();
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      const text = (current as typeof current & { revision_request?: string }).revision_request;
      if (text) history.unshift({ id: current.id, request: text, response: `수정 후 다시 실행했습니다. · v${current.code_version}` });
      current = current.parent_run_id ? runs.get(current.parent_run_id) : undefined;
    }
    return history;
  }, [session?.runs, run]);

  async function perform(label: string, work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(label);
    setError("");
    try { await work(); }
    catch (e) { setError((e as Error).message); }
    finally { inFlight.current = false; setBusy(""); }
  }

  function start() {
    if (!taskId) return;
    void perform("실행 중", async () => {
      const task = await api<TaskInput>(`/woz-tasks/${encodeURIComponent(taskId)}/input`);
      const next = await api<Session>(`/woz-tasks/${encodeURIComponent(taskId)}/start`, {
        input_csv: task.input_csv, target_csv: task.target_csv, condition: "ex",
      });
      accept(next);
      setStepId("");
      setFailures([]);
      setRequest("");
      if (next.status !== "ready") throw new Error(next.error?.message || "코드를 실행하지 못했습니다.");
    });
  }

  function revise() {
    const text = request.trim();
    if (!session || !run || !step || !text || !health?.api_configured || inFlight.current || taskChanged) return;
    const submitted: Message = { id: crypto.randomUUID(), request: text, response: "" };
    void perform("수정하고 실행하는 중", async () => {
      setPending(submitted);
      try {
        const next = await api<Session>(`/sessions/${session.id}/generate`, {
          request: text, scope, base_run_id: run.id,
          context: { step_id: step.id, selection: null },
        });
        accept(next);
        if (next.status !== "ready") throw new Error(next.error?.message || "수정을 적용하지 못했습니다. 다시 요청해 주세요.");
        setRequest("");
        if (composer.current) composer.current.style.height = "";
      } catch (e) {
        setFailures((items) => [...items, { ...submitted, failed: true, response: (e as Error).message }]);
      } finally { setPending(null); }
    });
  }

  function selectStep(id: string) { setStepId(id); }

  function resize(axis: keyof PanelSizes, delta: number) {
    setSizes((current) => {
      const limits = axis === "code" ? [25, 75] : axis === "chat" ? [20, 45] : [40, 85];
      const next = { ...current, [axis]: Math.min(limits[1], Math.max(limits[0], current[axis] + delta)) };
      localStorage.setItem("workspace-panels", JSON.stringify(next));
      return next;
    });
  }

  function drag(axis: keyof PanelSizes, event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const bounds = root.current!.getBoundingClientRect();
    const initial = sizes[axis];
    const origin = axis === "top" ? event.clientY : event.clientX;
    const length = axis === "top" ? bounds.height - 45 : axis === "code" ? bounds.width * (1 - sizes.chat / 100) : bounds.width;
    const direction = axis === "chat" ? -1 : 1;
    const target = event.currentTarget;
    const move = (e: PointerEvent) => {
      const point = axis === "top" ? e.clientY : e.clientX;
      const limits = axis === "code" ? [25, 75] : axis === "chat" ? [20, 45] : [40, 85];
      const value = Math.min(limits[1], Math.max(limits[0], initial + direction * (point - origin) / length * 100));
      setSizes((current) => { const next = { ...current, [axis]: value }; localStorage.setItem("workspace-panels", JSON.stringify(next)); return next; });
    };
    const stop = () => { target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", stop); target.removeEventListener("pointercancel", stop); };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", stop);
    target.addEventListener("pointercancel", stop);
  }

  const separator = (axis: keyof PanelSizes, label: string) => (
    <div className={`workspace-divider divider-${axis}`} role="separator" tabIndex={0}
      aria-label={label} aria-orientation={axis === "top" ? "horizontal" : "vertical"} aria-valuenow={Math.round(sizes[axis])}
      aria-valuemin={axis === "code" ? 25 : axis === "chat" ? 20 : 40} aria-valuemax={axis === "code" ? 75 : axis === "chat" ? 45 : 85}
      onPointerDown={(event) => drag(axis, event)} onKeyDown={(event: KeyboardEvent) => {
        const arrows = axis === "top" ? ["ArrowUp", "ArrowDown"] : ["ArrowLeft", "ArrowRight"];
        if (arrows.includes(event.key)) { event.preventDefault(); resize(axis, (event.key === arrows[0] ? -2 : 2) * (axis === "chat" ? -1 : 1)); }
      }} />
  );

  const tables = [{ id: "output", label: "결과", table: step?.table }, { id: "input", label: "Input", table: session?.input },
    ...Object.entries(session?.sources || {}).map(([name, table]) => ({ id: `source:${name}`, label: name, table })),
    ...(session?.target ? [{ id: "target", label: "Target", table: session.target }] : [])];
  const visibleTable = tables.find((item) => item.id === tableView)?.table;
  const canSend = !!request.trim() && !!run && !!step && !busy && !!health?.api_configured && !taskChanged;

  return (
    <div className="workspace" ref={root} style={{ "--code-size": `${sizes.code}%`, "--chat-size": `${sizes.chat}%`, "--top-size": `${sizes.top}%` } as CSSProperties}>
      <header className="workspace-toolbar">
        <select aria-label="과제 선택" className="task-select" disabled={booting || !!busy} value={taskId} onChange={(event) => setTaskId(event.target.value)}>
          {!tasks.some((task) => task.id === taskId) && <option value={taskId}>{booting ? "불러오는 중…" : session?.study_task?.title || "과제 선택"}</option>}
          {tasks.map((task) => <option key={task.id} value={task.id}>{taskLabel(task)}</option>)}
        </select>
        <Button size="sm" variant="outline" disabled={!taskId || !!busy || booting} onClick={start} title="저장된 코드 실행">
          {busy === "실행 중" ? <LoaderCircle className="animate-spin" /> : <Play />} 실행
        </Button>
        {taskChanged && <Button size="sm" variant="ghost" onClick={() => setTaskId(session!.task_id)}>취소</Button>}
        <div className="toolbar-spacer" />
        {run && <span className="version-label">v{run.code_version}</span>}
        <Button size="icon-sm" variant="ghost" aria-label="이전 실행으로 되돌리기" title="되돌리기" disabled={!!busy || !session || (!run?.parent_run_id && session.status !== "failed")} onClick={() => void perform("되돌리는 중", async () => {
          if (session) { accept(await api<Session>(`/sessions/${session.id}/undo`, {})); setFailures([]); }
        })}><RotateCcw /></Button>
        <Button size="icon-sm" variant="ghost" aria-label="결과 CSV 다운로드" title="CSV 다운로드" disabled={!run || !!busy} onClick={() => { location.href = `/api/sessions/${session!.id}/output.csv`; }}><Download /></Button>
      </header>
      <div className="workspace-main">
        <div className="workspace-left">
          <div className="workspace-top">
            <section className="code-pane" aria-label="Step별 코드">
              <div className="pane-toolbar"><span>Python</span><span className="pane-meta">{steps.length ? `${steps.length} steps` : ""}</span></div>
              <div className="code-list" ref={codeList} aria-busy={!!busy}>
                {steps.map((stage, index) => <article className="code-step" key={stage.id} data-selected={stage.id === step?.id}>
                  <button className="code-step-heading" aria-label={`Step ${index + 1} 선택`} aria-pressed={stage.id === step?.id} onClick={() => selectStep(stage.id)}>
                    <span>Step {String(index + 1).padStart(2, "0")}</span><span className="step-line-range">{stage.code_location ? `L${stage.code_location.start}–${stage.code_location.end}` : ""}</span>
                  </button>
                  <div className="step-code" onClick={() => selectStep(stage.id)}><PythonCode code={stage.code} /></div>
                </article>)}
                {!steps.length && <div className="pane-empty" role="status">{booting ? "불러오는 중…" : busy || "과제를 선택하고 실행하세요."}</div>}
              </div>
            </section>
            {separator("code", "코드와 테이블 너비 조절")}
            <section className="table-pane" aria-label="중간 테이블">
              <div className="pane-toolbar">
                <Button variant="ghost" size="icon-xs" aria-label="이전 Step" disabled={stepIndex <= 0 || !!busy} onClick={() => selectStep(steps[stepIndex - 1].id)}><ChevronLeft /></Button>
                <select className="step-select" aria-label="테이블 Step 선택" value={step?.id ?? ""} disabled={!steps.length || !!busy} onChange={(event) => selectStep(event.target.value)}>
                  {!steps.length && <option value="">Step</option>}
                  {steps.map((stage, index) => <option key={stage.id} value={stage.id}>Step {String(index + 1).padStart(2, "0")}</option>)}
                </select>
                <Button variant="ghost" size="icon-xs" aria-label="다음 Step" disabled={stepIndex < 0 || stepIndex >= steps.length - 1 || !!busy} onClick={() => selectStep(steps[stepIndex + 1].id)}><ChevronRight /></Button>
                <select className="table-view-select" aria-label="표 선택" disabled={!run} value={tableView} onChange={(event) => setTableView(event.target.value)}>{tables.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
                {visibleTable && <span className="pane-meta table-shape">{visibleTable.rows.length}행 × {visibleTable.columns.length}열</span>}
              </div>
              {visibleTable ? <WorkspaceTable data={visibleTable} identity={`${run?.id}:${step?.id}:${tableView}`} /> : <div className="pane-empty" />}
            </section>
          </div>
          {separator("top", "아래 빈 영역 높이 조절")}
          <section className="reserved-pane" aria-label="빈 영역" />
        </div>
        {separator("chat", "수정 요청 영역 너비 조절")}
        <section className="chat-pane" aria-label="자연어 수정 요청">
          <div className="pane-toolbar chat-toolbar"><span>수정 요청</span>{health && <span className="pane-meta" title={health.api_configured ? "서버 API 연결됨" : "서버 API 키 설정 필요"}><span className={`api-dot ${health.api_configured ? "connected" : ""}`} />{health.model}</span>}</div>
          <div className="chat-messages" role="log" aria-label="수정 요청 기록" aria-live="polite">
            {messages.map((message) => <ChatMessage key={message.id} message={message} />)}
            {failures.map((message) => <ChatMessage key={message.id} message={message} />)}
            {pending && <><div className="chat-request">{pending.request}</div><div className="chat-response chat-working"><LoaderCircle size={14} className="animate-spin" />{busy}</div></>}
            <div ref={chatEnd} />
          </div>
          <div className="chat-bottom">
            {error && <div className="workspace-error" role="alert"><span>{error}</span><button aria-label="오류 닫기" onClick={() => setError("")}><X size={14} /></button></div>}
            {session?.status === "failed" && !pending && <p className="composer-note" role="status">실행에 실패했습니다. 마지막 성공 결과를 표시합니다.</p>}
            {health && !health.api_configured && <p className="composer-note">수정 요청을 사용하려면 서버의 .env에 API 키를 설정하세요.</p>}
            <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); revise(); }}>
              <textarea ref={composer} aria-label="수정 요청 입력" placeholder="수정할 내용을 입력하세요" value={request} rows={3} maxLength={5000} disabled={!run || !!busy || taskChanged}
                onChange={(event) => { setRequest(event.target.value); event.target.style.height = "auto"; event.target.style.height = `${Math.min(220, event.target.scrollHeight)}px`; }}
                onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); revise(); } }} />
              <div className="composer-tools"><select aria-label="수정 범위" disabled={!run || !!busy} value={scope} onChange={(event) => setScope(event.target.value as Scope)}>
                <option value="step">Step {stepIndex >= 0 ? String(stepIndex + 1).padStart(2, "0") : ""}</option><option value="pipeline">전체 코드</option>
              </select><Button type="submit" size="icon-sm" aria-label="수정 요청 보내기" title="보내기 · Enter" disabled={!canSend}>{pending ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}</Button></div>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}

function ChatMessage({ message }: { message: Message }) {
  return <><div className="chat-request">{message.request}</div><div className={`chat-response ${message.failed ? "chat-failure" : ""}`}>{!message.failed && <Check size={14} />}{message.response}</div></>;
}
