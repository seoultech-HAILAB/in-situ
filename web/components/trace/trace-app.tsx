"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { ArrowUp, Check, ChevronLeft, ChevronRight, Download, LoaderCircle, Play, RotateCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api as traceApi, PythonCode, sourceSnippet, taskLabel, type Health, type Session, type TaskInput, type TaskSummary } from "@/lib/trace";
import { WorkspaceTable } from "./workspace-table";
import { ExSituExplanation } from "./ex-situ-explanation";
import { DirectUsedTables } from "./direct-used-tables";
import { workspaceSteps } from "./revision-workspace";

type Message = { id: string; request: string; response: string; failed?: boolean };
type PanelSizes = { code: number; chat: number; top: number };
const DEFAULT_SIZES: PanelSizes = { code: 50, chat: 25, top: 73 };
const OUTPUT_VIEW_ID = "view:final-output";
const STEP_HEADER_TONES = [
  { background: "#eaf4f1", selected: "#d5e9e2" },
  { background: "#edf2fa", selected: "#dbe6f5" },
  { background: "#f2eef8", selected: "#e5dcf1" },
];

export function TraceApp({ condition = "ex" }: { condition?: "ex" | "in-situ" }) {
  const sessionKey = condition === "in-situ" ? "trace-in-situ-session" : "trace-woz-session";
  const panelKey = `workspace-panels:${condition}`;
  const api = <T,>(path: string, body?: unknown) => traceApi<T>(path, body, { explain: true });
  const [session, setSession] = useState<Session | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [taskId, setTaskId] = useState("");
  const [stepId, setStepId] = useState("");
  const [inputViewId, setInputViewId] = useState<string | null>(null);
  const [request, setRequest] = useState("");
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
  const preview = session?.pending_revision;
  const inputViews = session ? [
    { viewId: "view:input:main", viewLabel: "Input", name: "input_df", tableView: "input", table: session.input },
    ...Object.entries(session.sources ?? {}).map(([name,table]) => ({ viewId: `view:input:source:${name}`, viewLabel: `Input · ${name}`, name, tableView: `source:${name}`, table })),
  ] : [];
  const selectedInput = inputViews.find(view => view.viewId === inputViewId);
  // Code blocks and tables use the same actual execution stage.
  const steps = useMemo(() => workspaceSteps(run, preview), [run, preview]);
  const finalStep = steps.filter(stage => !stage.isCandidate).at(-1);
  const viewingOutput = !selectedInput && condition === "in-situ" && stepId === OUTPUT_VIEW_ID && !!finalStep;
  const step = viewingOutput ? finalStep : steps.find((stage) => stage.viewId === stepId) ?? steps[0];
  const selectedViewId = selectedInput?.viewId ?? (viewingOutput ? OUTPUT_VIEW_ID : step?.viewId);
  const views = [...inputViews, ...steps, ...(condition === "in-situ" && finalStep ? [{ viewId: OUTPUT_VIEW_ID, viewLabel: "Output" }] : [])];
  const viewIndex = views.findIndex(view => view.viewId === selectedViewId);
  const observedVersion = step?.execution_version ?? run?.id;
  const originalStep = run?.stages.find(stage => stage.id === step?.id);
  const taskChanged = !!session && taskId !== session.task_id;

  function accept(next: Session) {
    setSession(next);
    setTaskId(next.task_id);
    localStorage.setItem(sessionKey, next.id);
    const url = new URL(location.href);
    url.searchParams.set("session", next.id);
    history.replaceState(null, "", url);
  }

  useEffect(() => {
    let active = true;
    try {
      const stored = JSON.parse(localStorage.getItem(panelKey) || localStorage.getItem("workspace-panels") || "null");
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
        const sid = new URLSearchParams(location.search).get("session") || localStorage.getItem(sessionKey);
        if (!sid) return;
        try {
          const restored = await api<Session>(`/sessions/${encodeURIComponent(sid)}`);
          if (active) accept(restored);
        } catch {
          if (!active) return;
          localStorage.removeItem(sessionKey);
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

  // A restored tab can observe a request still running in another tab/process.
  useEffect(() => {
    if (!session || !preview || !["generating", "approving"].includes(preview.status)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const latest = await traceApi<Session>(`/sessions/${session.id}`, undefined, { explain: false });
        if (active) {
          accept(latest);
          if (!latest.pending_revision) setStepId(preview.step_id);
        }
      } catch { /* Keep the observed snapshots available through reconnects. */ }
      finally { if (active) timer = setTimeout(poll, 2000); }
    };
    timer = setTimeout(poll, 2000);
    return () => { active = false; clearTimeout(timer); };
  }, [session?.id, preview?.id, preview?.status]);

  useEffect(() => {
    codeList.current?.querySelector<HTMLElement>("[data-selected=true]")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedViewId, observedVersion]);
  useEffect(() => { setTableView(selectedInput?.tableView ?? "output"); }, [observedVersion]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [pending, failures, run?.id, preview?.id, preview?.status]);

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
        input_csv: task.input_csv, target_csv: task.target_csv, condition,
      });
      accept(next);
      setStepId("");
      setInputViewId(null);
      setFailures([]);
      setRequest("");
      if (next.status !== "ready") throw new Error(next.error?.message || "코드를 실행하지 못했습니다.");
    });
  }

  function revise() {
    const text = request.trim();
    if (!session || !run || !step || selectedInput || preview || !text || !health?.api_configured || inFlight.current || taskChanged) return;
    const submitted: Message = { id: crypto.randomUUID(), request: text, response: "" };
    void perform("수정하고 실행하는 중", async () => {
      setPending(submitted);
      try {
        const next = await api<Session>(`/sessions/${session.id}/revision-preview`, {
          request: text, base_run_id: run.id,
          context: { step_id: step.id, selection: null },
        });
        accept(next);
        if (next.pending_revision?.status === "failed") return;
        if (next.pending_revision?.stage) setStepId(`preview:${next.pending_revision.id}`);
        setRequest("");
        if (composer.current) composer.current.style.height = "";
      } catch (e) {
        setFailures((items) => [...items, { ...submitted, failed: true, response: (e as Error).message }]);
      } finally { setPending(null); }
    });
  }

  function selectStep(id: string) {
    const input = inputViews.find(view => view.viewId === id);
    setInputViewId(input?.viewId ?? null);
    if (!input) setStepId(id);
    setTableView(input?.tableView ?? "output");
  }

  function selectTable(id: string) {
    setInputViewId(inputViews.find(view => view.tableView === id)?.viewId ?? null);
    setTableView(id);
  }

  function decide(action: "approve" | "deny") {
    if (!session || !preview) return;
    void perform(action === "approve" ? "전체 파이프라인 실행 중" : "후보 폐기 중", async () => {
      const next = await traceApi<Session>(`/sessions/${session.id}/revision-preview/${preview.id}/${action}`, {}, { explain: action === "approve" });
      accept(next);
      if (!next.pending_revision) setStepId(preview.step_id);
      if (next.pending_revision?.error) throw new Error(next.pending_revision.error);
    });
  }

  function resize(axis: keyof PanelSizes, delta: number) {
    setSizes((current) => {
      const limits = axis === "code" ? [25, 75] : axis === "chat" ? [20, 45] : [40, 85];
      const next = { ...current, [axis]: Math.min(limits[1], Math.max(limits[0], current[axis] + delta)) };
      localStorage.setItem(panelKey, JSON.stringify(next));
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
      setSizes((current) => { const next = { ...current, [axis]: value }; localStorage.setItem(panelKey, JSON.stringify(next)); return next; });
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
  const canSend = !!request.trim() && !!run && !!step && !selectedInput && !preview && !busy && !!health?.api_configured && !taskChanged;
  const tableContent = visibleTable ? <WorkspaceTable key={`${observedVersion}:${selectedViewId}:${tableView}`} data={visibleTable} identity={`${observedVersion}:${selectedViewId}:${tableView}`} stage={condition === "in-situ" && !selectedInput && !viewingOutput && tableView === "output" ? step : undefined}
    comparison={!selectedInput && !viewingOutput && step?.isCandidate ? originalStep?.table : undefined} /> : <div className="pane-empty" />;

  return (
    <div className={`workspace workspace-${condition === "in-situ" ? "in-situ" : "ex-situ"}`} ref={root} style={{ "--code-size": `${sizes.code}%`, "--chat-size": `${sizes.chat}%`, "--top-size": `${sizes.top}%` } as CSSProperties}>
      <header className="workspace-toolbar">
        <span className="workspace-mode">{condition === "in-situ" ? "In-situ" : "Ex-situ"}</span>
        <select aria-label="과제 선택" className="task-select" disabled={booting || !!busy || !!preview} value={taskId} onChange={(event) => setTaskId(event.target.value)}>
          {!tasks.some((task) => task.id === taskId) && <option value={taskId}>{booting ? "불러오는 중…" : session?.study_task?.title || "과제 선택"}</option>}
          {tasks.map((task) => <option key={task.id} value={task.id}>{taskLabel(task)}</option>)}
        </select>
        <Button size="sm" variant="outline" disabled={!taskId || !!busy || !!preview || booting} onClick={start} title="저장된 코드 실행">
          {busy === "실행 중" ? <LoaderCircle className="animate-spin" /> : <Play />} 실행
        </Button>
        {taskChanged && <Button size="sm" variant="ghost" onClick={() => setTaskId(session!.task_id)}>취소</Button>}
        <div className="toolbar-spacer" />
        {run && <span className="version-label">v{run.code_version}</span>}
        <Button size="icon-sm" variant="ghost" aria-label="이전 실행으로 되돌리기" title="되돌리기" disabled={!!busy || !!preview || !session || (!run?.parent_run_id && session.status !== "failed")} onClick={() => void perform("되돌리는 중", async () => {
          if (session) { accept(await api<Session>(`/sessions/${session.id}/undo`, {})); setFailures([]); }
        })}><RotateCcw /></Button>
        <Button size="icon-sm" variant="ghost" aria-label="결과 CSV 다운로드" title="확정 결과 CSV 다운로드" disabled={!run} onClick={() => { location.href = `/api/sessions/${session!.id}/output.csv`; }}><Download /></Button>
      </header>
      <div className="workspace-main">
        <div className="workspace-left">
          <div className="workspace-top">
            <section className="code-pane" aria-label="Step별 코드">
              <div className="pane-toolbar"><span>Python</span><span className="pane-meta">{run ? `${run.stages.length - 1} steps` : ""}</span></div>
              <div className="code-list" ref={codeList} aria-busy={!!busy}>
                {!!inputViews.length && <section className="code-input-section" aria-label="입력 테이블 목록">
                  <h2 className="input-section-heading"><span>Input</span><span>{inputViews.length}개 테이블</span></h2>
                  {inputViews.map(input => <button className="input-table-heading" key={input.viewId} aria-label={`${input.viewLabel} 입력 표 보기`}
                    aria-pressed={input.viewId === selectedViewId} data-selected={input.viewId === selectedViewId} onClick={() => selectStep(input.viewId)}>
                    <span className="input-table-name">{input.name}</span><span className="input-table-shape">{input.table.rows.length}행 × {input.table.columns.length}열</span>
                  </button>)}
                </section>}
                {steps.map((stage,index) => <article className={`code-step ${stage.isCandidate ? "code-step-candidate" : ""}`} key={stage.viewId} data-selected={stage.viewId === selectedViewId}
                  style={stage.isCandidate ? undefined : { "--step-heading-bg": STEP_HEADER_TONES[((stage.order || index+1)-1)%STEP_HEADER_TONES.length].background, "--step-heading-selected": STEP_HEADER_TONES[((stage.order || index+1)-1)%STEP_HEADER_TONES.length].selected } as CSSProperties}>
                  <button className="code-step-heading" aria-label={`${stage.viewLabel} 선택`} aria-pressed={stage.viewId === selectedViewId} onClick={() => selectStep(stage.viewId)}>
                    <span className="step-heading-number">{stage.viewLabel}{stage.isCandidate && <span className="candidate-badge">수정 후보</span>}</span>
                    {stage.nl_explanation?.title && <span className="step-heading-title">{stage.nl_explanation.title}</span>}
                    <span className="step-line-range">{stage.code_location ? `L${stage.code_location.start}–${stage.code_location.end}` : ""}</span>
                  </button>
                  <div className="step-code" onClick={() => selectStep(stage.viewId)}><PythonCode code={stage.viewCode ?? sourceSnippet(run?.code, stage.code, stage.code_location)} startLine={stage.code_location?.start ?? 1} plain={condition === "ex"} /></div>
                </article>)}
                {condition === "in-situ" && finalStep && <article className="code-output-section" data-selected={viewingOutput}>
                  <button className="output-heading" aria-label="Output 선택" aria-pressed={viewingOutput} onClick={() => selectStep(OUTPUT_VIEW_ID)}><span>Output</span><span className="step-line-range">최종 실행 결과</span></button>
                  <p className="output-summary">{finalStep.table.rows.length}행 × {finalStep.table.columns.length}열</p>
                </article>}
                {!steps.length && <div className="pane-empty" role="status">{booting ? "불러오는 중…" : busy || "과제를 선택하고 실행하세요."}</div>}
              </div>
            </section>
            {separator("code", "코드와 테이블 너비 조절")}
            <section className="table-pane" aria-label={selectedInput ? "입력 테이블" : viewingOutput ? "최종 결과 테이블" : "중간 테이블"}>
              <div className="pane-toolbar">
                <Button variant="ghost" size="icon-xs" aria-label="이전 Step" disabled={viewIndex <= 0} onClick={() => selectStep(views[viewIndex - 1].viewId)}><ChevronLeft /></Button>
                <select className="step-select" aria-label="테이블 Step 선택" value={selectedViewId ?? ""} disabled={!views.length} onChange={(event) => selectStep(event.target.value)}>
                  {!views.length && <option value="">Step</option>}
                  {views.map((view) => <option key={view.viewId} value={view.viewId}>{view.viewLabel}</option>)}
                </select>
                <Button variant="ghost" size="icon-xs" aria-label="다음 Step" disabled={viewIndex < 0 || viewIndex >= views.length - 1} onClick={() => selectStep(views[viewIndex + 1].viewId)}><ChevronRight /></Button>
                <select className="table-view-select" aria-label="표 선택" disabled={!session} value={tableView} onChange={(event) => selectTable(event.target.value)}>{tables.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
                {visibleTable && <span className="pane-meta table-shape">{visibleTable.rows.length}행 × {visibleTable.columns.length}열</span>}
              </div>
              {!selectedInput && step?.isCandidate && tableView === "output" && <div className="candidate-comparison-note">{step.viewLabel} · {originalStep ? `Step ${originalStep.order} 수정 전 결과와 비교` : "수정 후보 실행 결과"}</div>}
              {condition === "in-situ" && !selectedInput && !viewingOutput && tableView === "output" && !!step?.direct_tables?.length ? <div className="table-result-stack">
                <div className="direct-table-result">{tableContent}</div>
                <DirectUsedTables tables={step.direct_tables} identity={`${observedVersion}:${step.viewId}`} />
              </div> : tableContent}
            </section>
          </div>
          {condition === "ex" && <>
            {separator("top", "코드·테이블과 설명 높이 조절")}
            <ExSituExplanation step={selectedInput ? undefined : step} number={step?.order ?? 0} label={selectedInput?.viewLabel ?? step?.viewLabel} inputView={!!selectedInput} />
          </>}
        </div>
        {separator("chat", "수정 요청 영역 너비 조절")}
        <section className="chat-pane" aria-label="자연어 수정 요청">
          <div className="pane-toolbar chat-toolbar"><span>수정 요청</span>{health && <span className="pane-meta" title={health.api_configured ? "서버 API 연결됨" : "서버 API 키 설정 필요"}><span className={`api-dot ${health.api_configured ? "connected" : ""}`} />{health.model}</span>}</div>
          <div className="chat-messages" role="log" aria-label="수정 요청 기록" aria-live="polite">
            {messages.map((message) => <ChatMessage key={message.id} message={message} />)}
            {failures.map((message) => <ChatMessage key={message.id} message={message} />)}
            {pending && <><div className="chat-request">{pending.request}</div><div className="chat-response chat-working"><LoaderCircle size={14} className="animate-spin" />{busy}</div></>}
            {preview && <div className="revision-chat-review" aria-label="수정 후보 확인">
              <div className="chat-request">{preview.request}</div>
              <div className="chat-response revision-review-card">
                <strong>{preview.label} · {preview.status === "failed" ? "후보 실행 실패" : preview.status === "generating" ? "후보 생성 중" : preview.status === "approving" ? "전체 파이프라인 실행 중" : "승인 대기"}</strong>
                <p>{preview.status === "failed" ? preview.error : "기존 코드와 결과를 유지하고 있습니다. Step을 전환해 수정 전후를 비교할 수 있습니다."}</p>
                {preview.assumptions?.map((text,index) => <p key={index}>{text}</p>)}
                {preview.error && preview.status !== "failed" && <p role="alert">{preview.error}</p>}
                <div className="revision-actions">
                  <Button size="sm" disabled={!!busy || preview.status !== "ready"} onClick={() => decide("approve")}><Check />Approve</Button>
                  <Button size="sm" variant="outline" disabled={!!busy || !["ready","failed"].includes(preview.status)} onClick={() => decide("deny")}><X />Deny</Button>
                </div>
                {busy && <p role="status">{busy}</p>}
              </div>
            </div>}
            <div ref={chatEnd} />
          </div>
          <div className="chat-bottom">
            {error && <div className="workspace-error" role="alert"><span>{error}</span><button aria-label="오류 닫기" onClick={() => setError("")}><X size={14} /></button></div>}
            {session?.status === "failed" && !pending && <p className="composer-note" role="status">실행에 실패했습니다. 마지막 성공 결과를 표시합니다.</p>}
            {health && !health.api_configured && <p className="composer-note">수정 요청을 사용하려면 서버의 .env에 API 키를 설정하세요.</p>}
            <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); revise(); }}>
              <textarea ref={composer} aria-label="수정 요청 입력" placeholder={selectedInput ? "수정할 Step을 선택하세요" : preview ? "후보 승인 또는 거부 후 새 수정을 요청하세요" : "수정할 내용을 입력하세요"} value={request} rows={3} maxLength={5000} disabled={!run || !!selectedInput || !!busy || !!preview || taskChanged}
                onChange={(event) => { setRequest(event.target.value); event.target.style.height = "auto"; event.target.style.height = `${Math.min(220, event.target.scrollHeight)}px`; }}
                onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); revise(); } }} />
              <div className="composer-tools"><span className="composer-step" aria-label={selectedInput ? "현재 관찰 중인 입력" : "현재 관찰 중인 Step"} aria-live="polite">{selectedInput?.viewLabel ?? step?.viewLabel ?? "Step —"}</span><Button type="submit" size="icon-sm" aria-label="수정 요청 보내기" title="보내기 · Enter" disabled={!canSend}>{pending ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}</Button></div>
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
