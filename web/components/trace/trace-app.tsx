"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactElement, type ReactNode } from "react";
import { ArrowUp, Check, ChevronLeft, ChevronRight, CircleAlert, Download, History, LoaderCircle, MessageSquare, PanelBottom, PanelLeft, Play, RotateCcw, Search, Table2, X } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandShortcut } from "@/components/ui/command";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api as traceApi, PythonCode, sourceSnippet, taskLabel, type Health, type Session, type Stage, type Table, type TaskInput, type TaskSummary } from "@/lib/trace";
import { WorkspaceTable } from "./workspace-table";
import type { Transformation } from "./workspace-diff";
import { asRunChange, changeSummary, CodeDiff } from "./code-diff";

type Scope = "step" | "pipeline";
type Message = { id: string; request: string; response: string; failed?: boolean };
type PanelSizes = { code: number; chat: number; top: number };
type View = "explorer" | "timeline";
const DEFAULT_SIZES: PanelSizes = { code: 50, chat: 26, top: 66 };
const LIMITS: Record<keyof PanelSizes, [number, number]> = { code: [25, 75], chat: [20, 45], top: [35, 90] };
const stepLabel = (index: number) => `Step ${String(index + 1).padStart(2, "0")}`;
const mod = (event: globalThis.KeyboardEvent) => event.metaKey || event.ctrlKey;

/** Icon button with a delayed label and its shortcut, so every control explains itself on hover or focus. */
function Tip({ label, keys, children }: { label: string; keys?: string[]; children: ReactElement }) {
  return <Tooltip>
    <TooltipTrigger render={children} />
    <TooltipContent>{label}{keys && <KbdGroup>{keys.map((k) => <Kbd key={k}>{k}</Kbd>)}</KbdGroup>}</TooltipContent>
  </Tooltip>;
}

export function TraceApp({ condition = "ex" }: { condition?: "ex" | "in-situ" }) {
  const sessionKey = condition === "in-situ" ? "trace-in-situ-session" : "trace-woz-session";
  const api = <T,>(path: string, body?: unknown) => traceApi<T>(path, body, { explain: condition === "in-situ" });
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
  const [notes, setNotes] = useState<Message[]>([]);
  const [sizes, setSizes] = useState<PanelSizes>(DEFAULT_SIZES);
  const [view, setView] = useState<View>("explorer");
  const [sidebar, setSidebar] = useState(true);
  const [panel, setPanel] = useState<string | null>("target");
  const [chatOpen, setChatOpen] = useState(true);
  const [palette, setPalette] = useState(false);
  const codeList = useRef<HTMLDivElement>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const inFlight = useRef(false);
  const run = session?.run;
  const candidate = session?.preview;
  // Code blocks and tables use the same actual execution stage.
  const steps = useMemo(() => run?.stages.filter((stage) => stage.kind !== "input") ?? [], [run]);
  const step = steps.find((stage) => stage.id === stepId) ?? steps[0];
  const stepIndex = steps.findIndex((stage) => stage.id === step?.id);
  const taskChanged = !!session && taskId !== session.task_id;
  const [editTarget, setEditTarget] = useState<{ id: string; step: string; run: string; line?: { start: number; end: number } } | null>(null);
  const selectedOperation = editTarget?.step === step?.id && editTarget?.run === run?.id ? editTarget : null;
  useEffect(() => { setEditTarget(null); }, [run?.id, step?.id]);
  const selectTransformation = useCallback((item: Transformation) => {
    if (!item.id || !run || !step) return;
    setEditTarget((current) => current && current.id === item.id && current.run === run.id ? current : { id: item.id!, step: step.id, run: run.id, line: item.line });
    setScope("step");
  }, [run?.id, step?.id]);

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
      const stored = JSON.parse(localStorage.getItem("workspace-panels") || "null");
      if (stored && (Object.keys(LIMITS) as (keyof PanelSizes)[]).every((key) => Number.isFinite(stored[key])))
        setSizes(Object.fromEntries((Object.keys(LIMITS) as (keyof PanelSizes)[]).map((key) => [key, Math.min(LIMITS[key][1], Math.max(LIMITS[key][0], stored[key]))])) as PanelSizes);
      const chrome = JSON.parse(localStorage.getItem("workspace-chrome") || "null");
      if (chrome) { setSidebar(chrome.sidebar !== false); setPanel(chrome.panel ?? null); setChatOpen(chrome.chat !== false); }
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

  useEffect(() => { localStorage.setItem("workspace-chrome", JSON.stringify({ sidebar, panel, chat: chatOpen })); }, [sidebar, panel, chatOpen]);

  useEffect(() => {
    codeList.current?.querySelector<HTMLElement>("[data-selected=true]")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [step?.id, run?.id]);
  useEffect(() => {
    // Vertical only: scrollIntoView would also slide the code sideways under the gutter.
    const list = codeList.current, mark = list?.querySelector<HTMLElement>(".python-line-mark");
    if (list && mark) { const a = mark.getBoundingClientRect(), b = list.getBoundingClientRect(); list.scrollBy({ top: a.top - b.top - b.height / 2 + a.height / 2, behavior: "smooth" }); }
  }, [selectedOperation?.id]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [pending, notes, run?.id, candidate?.run.id]);

  // Follow ancestry so undo and forks show only the current execution's history.
  const messages = useMemo(() => {
    const history: (Message & { version: number })[] = [];
    const runs = new Map(session?.runs.map((item) => [item.id, item]));
    let current = run;
    const seen = new Set<string>();
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      const text = (current as typeof current & { revision_request?: string }).revision_request;
      history.unshift({ id: current.id, version: current.code_version, request: text || "", response: text ? `수정안을 적용했습니다. 지금 결과는 v${current.code_version}입니다.` : "" });
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
      setNotes([]);
      setRequest("");
      if (next.status !== "ready") throw new Error(next.error?.message || "코드를 실행하지 못했습니다.");
    });
  }

  // Revisions come back as a candidate; the current result stays until the participant applies it.
  function revise() {
    const text = request.trim();
    if (!session || !run || !step || !text || !health?.api_configured || inFlight.current || taskChanged) return;
    const submitted: Message = { id: crypto.randomUUID(), request: text, response: "" };
    void perform("수정안을 만들고 실행하는 중", async () => {
      setPending(submitted);
      setRequest("");
      try {
        const next = await api<Session>(`/sessions/${session.id}/generate`, {
          request: text, scope, base_run_id: run.id, preview: true,
          context: { step_id: step.id, selection: null, ...(selectedOperation ? { transformation_id: selectedOperation.id, execution_version: run.id } : {}) },
        });
        accept(next);
        if (next.status !== "ready" || !next.preview) throw new Error(next.error?.message || "수정을 적용하지 못했습니다. 다시 요청해 주세요.");
        if (composer.current) composer.current.style.height = "";
      } catch (e) {
        setRequest(text); // Keep the wording so a failed request is one edit away from a retry.
        setNotes((items) => [...items, { ...submitted, failed: true, response: (e as Error).message }]);
      } finally { setPending(null); }
    });
  }

  function decide(decision: "apply" | "discard") {
    if (!session || !candidate) return;
    const asked = candidate.request;
    void perform(decision === "apply" ? (condition === "in-situ" ? "적용하고 변환 설명을 준비하는 중" : "적용 중") : "취소 중", async () => {
      const next = await api<Session>(`/sessions/${session.id}/preview/${decision}`, { run_id: candidate.run.id });
      accept(next);
      if (decision === "apply") toast.success(`수정안을 적용했습니다 · v${next.run?.code_version}`);
      else {
        setNotes((items) => [...items, { id: crypto.randomUUID(), request: asked, response: "수정안을 취소했습니다. 이전 결과를 그대로 둡니다." }]);
        toast("수정안을 취소했습니다");
      }
    });
  }

  function undo() {
    if (!session) return;
    void perform("되돌리는 중", async () => {
      const next = await api<Session>(`/sessions/${session.id}/undo`, {});
      accept(next);
      setNotes([]);
      toast(`이전 실행으로 되돌렸습니다 · v${next.run?.code_version}`);
    });
  }

  const tables = useMemo(() => [
    { id: "input", label: "Input", table: session?.input },
    ...Object.entries(session?.sources || {}).map(([name, table]) => ({ id: `source:${name}`, label: name, table })),
    ...(session?.target ? [{ id: "target", label: "Target", table: session.target }] : []),
  ].filter((item): item is { id: string; label: string; table: Table } => !!item.table), [session?.input, session?.sources, session?.target]);
  const panelTable = tables.find((item) => item.id === panel);
  const togglePanel = useCallback(() => setPanel((current) => (current ? null : tables.find((t) => t.id === "target")?.id ?? "output")), [tables]);
  const focusComposer = () => { setChatOpen(true); requestAnimationFrame(() => composer.current?.focus()); };

  useEffect(() => {
    const keys = (event: globalThis.KeyboardEvent) => {
      if (!mod(event) || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "b") { event.preventDefault(); setSidebar((v) => !v); }
      else if (key === "j") { event.preventDefault(); togglePanel(); }
      else if ((key === "k" || key === "p") && !event.shiftKey) { event.preventDefault(); setPalette((v) => !v); }
      else if (key === "i") { event.preventDefault(); focusComposer(); }
    };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  }, [togglePanel]);

  function resize(axis: keyof PanelSizes, delta: number) {
    setSizes((current) => {
      const [min, max] = LIMITS[axis];
      const next = { ...current, [axis]: Math.min(max, Math.max(min, current[axis] + delta)) };
      localStorage.setItem("workspace-panels", JSON.stringify(next));
      return next;
    });
  }

  function drag(axis: keyof PanelSizes, event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    // The divider's own container is the length being split.
    const bounds = target.parentElement!.getBoundingClientRect();
    const initial = sizes[axis];
    const origin = axis === "top" ? event.clientY : event.clientX;
    const length = axis === "top" ? bounds.height : bounds.width;
    const direction = axis === "chat" ? -1 : 1;
    const move = (e: PointerEvent) => {
      const point = axis === "top" ? e.clientY : e.clientX;
      const [min, max] = LIMITS[axis];
      const value = Math.min(max, Math.max(min, initial + direction * (point - origin) / length * 100));
      setSizes((current) => { const next = { ...current, [axis]: value }; localStorage.setItem("workspace-panels", JSON.stringify(next)); return next; });
    };
    const stop = () => { target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", stop); target.removeEventListener("pointercancel", stop); };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", stop);
    target.addEventListener("pointercancel", stop);
  }

  const separator = (axis: keyof PanelSizes, label: string) => (
    <div className={`workspace-divider divider-${axis}`} role="separator" tabIndex={0} title="끌어서 크기 조절 · 두 번 누르면 원래 크기"
      aria-label={label} aria-orientation={axis === "top" ? "horizontal" : "vertical"} aria-valuenow={Math.round(sizes[axis])}
      aria-valuemin={LIMITS[axis][0]} aria-valuemax={LIMITS[axis][1]}
      onPointerDown={(event) => drag(axis, event)} onDoubleClick={() => resize(axis, DEFAULT_SIZES[axis] - sizes[axis])} onKeyDown={(event: KeyboardEvent) => {
        const arrows = axis === "top" ? ["ArrowUp", "ArrowDown"] : ["ArrowLeft", "ArrowRight"];
        if (arrows.includes(event.key)) { event.preventDefault(); resize(axis, (event.key === arrows[0] ? -2 : 2) * (axis === "chat" ? -1 : 1)); }
      }} />
  );

  // Preview: the candidate's version of the open step, compared with the current result.
  const candidateSteps = candidate?.run.stages.filter((stage) => stage.kind !== "input") ?? [];
  const candidateStep: Stage | undefined = candidate ? candidateSteps.find((s) => s.id === step?.id) ?? candidateSteps[stepIndex] ?? candidateSteps.at(-1) : undefined;
  const changedSteps = new Set(candidate ? steps.filter((s, i) => (candidateSteps.find((c) => c.id === s.id) ?? candidateSteps[i])?.code !== s.code).map((s) => s.id) : []);
  const lastStep = steps.at(-1), lastCandidate = candidateSteps.at(-1);
  const summaries = candidateStep && step ? [
    { label: `${stepLabel(stepIndex)} 결과`, text: changeSummary(step.table, candidateStep) },
    ...(lastStep && lastCandidate && lastStep.id !== step.id ? [{ label: "최종 결과", text: changeSummary(lastStep.table, lastCandidate) }] : []),
  ] : [];
  const canSend = !!request.trim() && !!run && !!step && !busy && !!health?.api_configured && !taskChanged;
  const shownTable = candidate && candidateStep ? candidateStep.table : step?.table;
  const running = busy === "실행 중" || (booting && !run);
  const scopeItems = [{ value: "step", label: selectedOperation ? "선택한 연산만" : stepIndex >= 0 ? `${stepLabel(stepIndex)}만` : "이 Step만" }, { value: "pipeline", label: "전체 코드" }];

  return (
    <div className="app-shell flex h-dvh min-h-[420px] flex-col gap-2 overflow-hidden bg-background p-2 text-[13px]" style={{ "--code-size": `${sizes.code}%`, "--chat-size": `${sizes.chat}%`, "--top-size": `${sizes.top}%` } as CSSProperties}>
      <header className="flex h-10 shrink-0 items-center gap-2 px-1">
        <span className="pr-1 text-xs font-bold tracking-wide text-primary">TRACE</span>
        <Badge variant="secondary">{condition === "in-situ" ? "In-situ" : "Ex-situ"}</Badge>
        <Select items={tasks.map((t) => ({ value: t.id, label: taskLabel(t) }))} value={taskId || null} disabled={booting || !!busy} onValueChange={(value) => value && setTaskId(value as string)}>
          <SelectTrigger size="sm" aria-label="과제 선택" className="ml-2 w-[min(32vw,300px)] bg-card"><SelectValue placeholder={booting ? "불러오는 중…" : "과제 선택"} /></SelectTrigger>
          <SelectContent>{tasks.map((t) => <SelectItem key={t.id} value={t.id}>{taskLabel(t)}</SelectItem>)}</SelectContent>
        </Select>
        <Button size="sm" variant={run && !taskChanged ? "outline" : "default"} disabled={!taskId || !!busy || booting} onClick={start}>
          {busy === "실행 중" ? <LoaderCircle className="animate-spin" /> : <Play />}{run && !taskChanged ? "다시 실행" : "실행"}
        </Button>
        {taskChanged && <Button size="sm" variant="ghost" onClick={() => setTaskId(session!.task_id)}>선택 취소</Button>}
        <button type="button" onClick={() => setPalette(true)} className="mx-auto flex h-8 w-full max-w-sm items-center gap-2 rounded-lg border bg-card px-3 text-muted-foreground shadow-xs transition-colors hover:border-foreground/20 hover:text-foreground">
          <Search className="size-3.5" /><span className="truncate">Step이나 표로 이동</span><KbdGroup className="ml-auto"><Kbd>⌘</Kbd><Kbd>K</Kbd></KbdGroup>
        </button>
        <div className="flex items-center gap-1">
          {run && <Badge variant={candidate ? "outline" : "secondary"} className={candidate ? "border-amber-300 bg-amber-50 text-amber-800" : ""}>{candidate ? "수정안 검토 중" : `v${run.code_version}`}</Badge>}
          <Tip label="이전 실행으로 되돌리기"><Button size="icon-sm" variant="ghost" aria-label="이전 실행으로 되돌리기" disabled={!!busy || !session || (!run?.parent_run_id && session.status !== "failed")} onClick={undo}><RotateCcw /></Button></Tip>
          <Tip label="결과 CSV 내려받기"><Button size="icon-sm" variant="ghost" aria-label="결과 CSV 내려받기" disabled={!run || !!busy} onClick={() => { location.href = `/api/sessions/${session!.id}/output.csv`; }}><Download /></Button></Tip>
          <span className="mx-1 h-4 w-px bg-border" />
          <Tip label="사이드바" keys={["⌘", "B"]}><Button size="icon-sm" variant={sidebar ? "secondary" : "ghost"} aria-label="사이드바 열고 닫기" aria-pressed={sidebar} onClick={() => setSidebar((v) => !v)}><PanelLeft /></Button></Tip>
          <Tip label="아래 패널" keys={["⌘", "J"]}><Button size="icon-sm" variant={panel ? "secondary" : "ghost"} aria-label="아래 패널 열고 닫기" aria-pressed={!!panel} onClick={togglePanel}><PanelBottom /></Button></Tip>
          <Tip label="수정 요청" keys={["⌘", "I"]}><Button size="icon-sm" variant={chatOpen ? "secondary" : "ghost"} aria-label="수정 요청 열고 닫기" aria-pressed={chatOpen} onClick={() => setChatOpen((v) => !v)}><MessageSquare /></Button></Tip>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 gap-2">
        {sidebar && <aside className="surface flex w-60 shrink-0 flex-col" aria-label="사이드바">
          <Tabs value={view} onValueChange={(value) => setView(value as View)} className="p-2 pb-0">
            <TabsList className="w-full">
              <TabsTrigger value="explorer"><Table2 />탐색기</TabsTrigger>
              <TabsTrigger value="timeline"><History />실행 기록</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {view === "explorer" ? <>
              <p className="side-heading">데이터</p>
              <ul className="space-y-0.5">
                {tables.map((t) => <li key={t.id}><button type="button" className="side-item" data-selected={panel === t.id} onClick={() => setPanel(t.id)}>
                  <Table2 className="size-3.5 text-muted-foreground" /><span className="truncate">{t.label}</span><span className="side-meta">{t.table.rows.length}×{t.table.columns.length}</span>
                </button></li>)}
                {!tables.length && (running ? [0, 1, 2].map((i) => <Skeleton key={i} className="mx-2 my-1.5 h-4" />) : <li className="side-empty">과제를 실행하면 표가 나타납니다</li>)}
              </ul>
              <p className="side-heading mt-4">단계{steps.length ? <span className="side-meta">{steps.length}개</span> : null}</p>
              <ol className="space-y-0.5">
                {steps.map((s, i) => <li key={s.id}><button type="button" className="side-item" data-selected={s.id === step?.id} aria-current={s.id === step?.id ? "step" : undefined} onClick={() => setStepId(s.id)}>
                  <span className="step-dot">{i + 1}</span><span>{stepLabel(i)}</span>
                  {changedSteps.has(s.id) && <Badge variant="outline" className="h-4 border-amber-300 px-1.5 text-[10px] text-amber-800">변경</Badge>}
                  <span className="side-meta">{s.code_location ? `L${s.code_location.start}–${s.code_location.end}` : ""}</span>
                </button></li>)}
                {!steps.length && (running ? [0, 1, 2, 3].map((i) => <Skeleton key={i} className="mx-2 my-1.5 h-4" />) : <li className="side-empty">위에서 과제를 고르고 실행하세요</li>)}
              </ol>
            </> : <ol className="timeline">
              {candidate && <li data-kind="candidate"><span className="timeline-dot" /><div><p className="font-medium">수정안 · 검토 중</p><p className="text-muted-foreground">{candidate.request}</p></div></li>}
              {[...messages].reverse().map((m) => <li key={m.id} data-kind={m.id === run?.id ? "current" : undefined}><span className="timeline-dot" />
                <div><p className="font-medium">v{m.version}{m.id === run?.id ? " · 지금 결과" : ""}</p><p className="text-muted-foreground">{m.request || "처음 실행"}</p></div></li>)}
              {!messages.length && <li className="side-empty">아직 실행 기록이 없습니다</li>}
            </ol>}
          </div>
        </aside>}

        <div className={`workspace-main ${chatOpen ? "" : "chat-closed"}`}>
          <div className={`workspace-left ${panel ? "" : "panel-closed"}`}>
            <section className="surface flex min-h-0 flex-col" aria-label="코드와 결과">
              <div className="flex h-11 shrink-0 items-center gap-1 border-b px-2">
                <Tip label="이전 Step"><Button variant="ghost" size="icon-sm" aria-label="이전 Step" disabled={stepIndex <= 0 || !!busy} onClick={() => setStepId(steps[stepIndex - 1].id)}><ChevronLeft /></Button></Tip>
                {steps.length ? <Tabs value={step?.id ?? ""} onValueChange={(value) => setStepId(value as string)} className="min-w-0">
                  <TabsList className="max-w-full overflow-x-auto">
                    {steps.map((s, i) => <TabsTrigger key={s.id} value={s.id} className="px-2.5">{stepLabel(i)}{changedSteps.has(s.id) && <span className="size-1.5 rounded-full bg-amber-500" aria-label="수정안에서 바뀜" />}</TabsTrigger>)}
                  </TabsList>
                </Tabs> : <Skeleton className={running ? "h-7 w-64" : "hidden"} />}
                <Tip label="다음 Step"><Button variant="ghost" size="icon-sm" aria-label="다음 Step" disabled={stepIndex < 0 || stepIndex >= steps.length - 1 || !!busy} onClick={() => setStepId(steps[stepIndex + 1].id)}><ChevronRight /></Button></Tip>
                {step?.code_location && <span className="ml-auto pr-2 font-mono text-[11px] text-muted-foreground">L{step.code_location.start}–{step.code_location.end}</span>}
              </div>

              {candidate && step && <div className="m-2 mb-0 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2" role="region" aria-label="수정안 검토">
                <Badge className="bg-amber-500 text-white">수정안</Badge>
                <span className="min-w-0 max-w-[40%] truncate font-medium" title={candidate.request}>“{candidate.request}”</span>
                <span className="flex min-w-0 flex-1 flex-wrap gap-x-3 text-xs text-muted-foreground">{summaries.map((s) => <span key={s.label}><span className="text-foreground/70">{s.label}</span> {s.text}</span>)}</span>
                <div className="ml-auto flex gap-1.5">
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => decide("discard")}>취소</Button>
                  <Button size="sm" disabled={!!busy} onClick={() => decide("apply")}>{busy.startsWith("적용") ? <LoaderCircle className="animate-spin" /> : <Check />}적용</Button>
                </div>
              </div>}

              {step ? <div className="workspace-top">
                <section className="code-pane" aria-label={candidate ? "코드 변경 비교" : "Step별 코드"}>
                  {candidate ? <CodeDiff before={run!.code} after={candidate.run.code} /> :
                    <div className="code-list" ref={codeList} aria-busy={!!busy}>
                      {steps.map((stage, index) => <article className="code-step" key={stage.id} data-selected={stage.id === step.id}>
                        <button className="code-step-heading" aria-label={`${stepLabel(index)} 선택`} aria-pressed={stage.id === step.id} onClick={() => setStepId(stage.id)}>
                          <span>{stepLabel(index)}</span><span className="step-line-range">{stage.code_location ? `L${stage.code_location.start}–${stage.code_location.end}` : ""}</span>
                        </button>
                        <div className="step-code" onClick={() => setStepId(stage.id)}>
                          <PythonCode code={sourceSnippet(run?.code, stage.code, stage.code_location)} startLine={stage.code_location?.start ?? 1} mark={stage.id === step.id ? selectedOperation?.line : null} />
                        </div>
                      </article>)}
                    </div>}
                </section>
                {separator("code", "코드와 결과 너비 조절")}
                <section className="table-pane" aria-label={candidate ? "수정안 결과" : "Step 결과"}>
                  <div className="pane-toolbar">
                    <span className="font-medium text-foreground/80">{candidate ? "수정안 결과" : "결과"}</span>
                    {shownTable && <span className="pane-meta">{shownTable.rows.length}행 × {shownTable.columns.length}열</span>}
                  </div>
                  {candidate && candidateStep ? <WorkspaceTable key={`preview:${candidate.run.id}:${candidateStep.id}`} data={candidateStep.table} identity={`preview:${candidate.run.id}:${candidateStep.id}`}
                    stage={condition === "in-situ" ? asRunChange(step.table, candidateStep) : undefined} explain={false} /> :
                    <WorkspaceTable key={`${run?.id}:${step.id}`} data={step.table} identity={`${run?.id}:${step.id}`} stage={condition === "in-situ" ? step : undefined}
                      onTransformationSelect={selectTransformation} refreshing={!!busy} onRefresh={condition === "in-situ" && health?.api_configured && session && run ? () => void perform("변환 설명 갱신", async () => {
                        const next = await api<Session>(`/sessions/${session.id}/explanations`, { run_id: run.id, refresh_transformations: true });
                        accept(next);
                        if (next.run?.explanation_status === "failed") throw new Error(next.run.explanation_error || "변환 설명을 갱신하지 못했습니다.");
                      }) : undefined} />}
                </section>
              </div> : running ? <div className="grid flex-1 grid-cols-2 gap-6 p-6">
                <div className="space-y-3">{[80, 60, 72, 40, 66, 52].map((w, i) => <Skeleton key={i} className="h-3.5" style={{ width: `${w}%` }} />)}</div>
                <div className="space-y-2">{[0, 1, 2, 3, 4, 5, 6].map((i) => <Skeleton key={i} className="h-7" />)}</div>
              </div> : <EmptyEditor />}
            </section>

            {panel && <>
              {separator("top", "아래 패널 높이 조절")}
              <section className="surface flex min-h-0 flex-col" aria-label="데이터 패널">
                <div className="flex h-10 shrink-0 items-center gap-2 border-b px-2">
                  <Tabs value={panel} onValueChange={(value) => setPanel(value as string)}>
                    <TabsList variant="line">
                      {tables.map((t) => <TabsTrigger key={t.id} value={t.id} className="px-2 text-xs">{t.label}</TabsTrigger>)}
                      <TabsTrigger value="output" className="px-2 text-xs">실행 출력</TabsTrigger>
                    </TabsList>
                  </Tabs>
                  {panelTable && <span className="ml-auto text-xs text-muted-foreground">{panelTable.table.rows.length}행 × {panelTable.table.columns.length}열</span>}
                  <Tip label="패널 닫기" keys={["⌘", "J"]}><Button variant="ghost" size="icon-xs" className={panelTable ? "" : "ml-auto"} aria-label="패널 닫기" onClick={() => setPanel(null)}><X /></Button></Tip>
                </div>
                {panelTable ? <WorkspaceTable key={panelTable.id} data={panelTable.table} identity={panelTable.id} /> :
                  <ol className="flex-1 space-y-1 overflow-auto p-3 font-mono text-xs" aria-label="실행 출력">
                    {session?.runs.map((r) => <li key={r.id} className="flex items-center gap-3">
                      <span className="text-muted-foreground">{new Date(r.created_at).toLocaleTimeString("ko-KR", { hour12: false })}</span>
                      <span>v{r.code_version} 실행 완료 · {r.execution_ms}ms · 결과 {r.stages.at(-1)?.table.rows.length ?? 0}행</span>{r.id === run?.id && <Badge variant="secondary" className="h-4 text-[10px]">지금 결과</Badge>}
                    </li>)}
                    {candidate && <li className="flex gap-3"><span className="text-muted-foreground">{new Date(candidate.at).toLocaleTimeString("ko-KR", { hour12: false })}</span><span className="text-amber-800">수정안 실행 완료 · 적용 대기</span></li>}
                    {session?.status === "failed" && <li className="text-destructive">마지막 실행 실패: {session.error?.message}</li>}
                    {!session && <li className="text-muted-foreground">실행 기록이 여기에 표시됩니다</li>}
                  </ol>}
              </section>
            </>}
          </div>

          {chatOpen && <>
            {separator("chat", "수정 요청 너비 조절")}
            <section className="surface flex min-h-0 flex-col" aria-label="자연어 수정 요청">
              <div className="flex h-11 shrink-0 items-center gap-2 border-b px-3">
                <span className="font-medium">수정 요청</span>
                {health && <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground" title={health.api_configured ? "서버 API 연결됨" : "서버 API 키 설정 필요"}><span className={`api-dot ${health.api_configured ? "connected" : ""}`} />{health.model}</span>}
                <Tip label="닫기" keys={["⌘", "I"]}><Button variant="ghost" size="icon-xs" className={health ? "" : "ml-auto"} aria-label="수정 요청 닫기" onClick={() => setChatOpen(false)}><X /></Button></Tip>
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3" role="log" aria-label="수정 요청 기록" aria-live="polite">
                {messages.filter((m) => m.request).map((message) => <ChatMessage key={message.id} message={message} />)}
                {notes.map((message) => <ChatMessage key={message.id} message={message} />)}
                {candidate && !pending && <ChatMessage message={{ id: "candidate", request: candidate.request, response: "수정안을 실행했습니다. 왼쪽에서 바뀌는 코드와 결과를 확인한 뒤 적용하거나 취소하세요." }} waiting />}
                {pending && <><div className="bubble-user">{pending.request}</div><div className="flex items-center gap-2 text-xs text-muted-foreground"><LoaderCircle className="size-3.5 animate-spin" />{busy}</div></>}
                {!messages.some((m) => m.request) && !notes.length && !pending && !candidate && <ChatIntro inSitu={condition === "in-situ"} />}
                <div ref={chatEnd} />
              </div>
              <div className="shrink-0 space-y-2 p-3 pt-0">
                {error && <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-xs leading-relaxed text-destructive" role="alert"><CircleAlert className="mt-0.5 size-3.5 shrink-0" /><span className="flex-1">{error}</span><button className="shrink-0" aria-label="오류 닫기" onClick={() => setError("")}><X className="size-3.5" /></button></div>}
                {session?.status === "failed" && !pending && <p className="text-xs text-amber-800" role="status">실행에 실패했습니다. 마지막 성공 결과를 보여 줍니다.</p>}
                {health && !health.api_configured && <p className="text-xs text-amber-800">수정 요청을 쓰려면 서버의 .env에 API 키를 설정하세요.</p>}
                <form className="rounded-xl border bg-background shadow-xs transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/15" onSubmit={(event) => { event.preventDefault(); revise(); }}>
                  {selectedOperation && <div className="m-2 mb-0 flex items-center gap-1.5 rounded-md bg-accent px-2 py-1 text-xs text-accent-foreground">
                    <span>대상: 선택한 연산{selectedOperation.line ? ` · L${selectedOperation.line.start}` : ""}</span>
                    <button type="button" className="ml-auto rounded p-0.5 hover:bg-background/60" aria-label="연산 선택 해제" onClick={() => setEditTarget(null)}><X className="size-3" /></button>
                  </div>}
                  <textarea ref={composer} aria-label="수정 요청 입력" className="block max-h-56 min-h-20 w-full resize-none bg-transparent px-3 py-2.5 leading-relaxed outline-none placeholder:text-muted-foreground disabled:opacity-60"
                    placeholder={candidate ? "다시 요청하면 지금 수정안을 대신합니다" : run ? "어떻게 바뀌어야 하는지 적어 주세요" : "과제를 실행한 뒤 요청할 수 있습니다"} value={request} rows={3} maxLength={5000} disabled={!run || !!busy || taskChanged}
                    onChange={(event) => { setRequest(event.target.value); event.target.style.height = "auto"; event.target.style.height = `${Math.min(224, event.target.scrollHeight)}px`; }}
                    onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); revise(); } }} />
                  <div className="flex items-center gap-2 px-2 pb-2">
                    <Select items={scopeItems} value={scope} disabled={!run || !!busy} onValueChange={(value) => setScope(value as Scope)}>
                      <SelectTrigger size="sm" aria-label="수정 범위" className="h-7 border-transparent bg-muted text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>{scopeItems.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent>
                    </Select>
                    <Tip label="보내기 · 줄바꿈은 Shift+Enter" keys={["Enter"]}><Button type="submit" size="icon-sm" className="ml-auto rounded-full" aria-label="수정 요청 보내기" disabled={!canSend}>{pending ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}</Button></Tip>
                  </div>
                </form>
              </div>
            </section>
          </>}
        </div>
      </div>

      <CommandDialog open={palette} onOpenChange={setPalette} title="이동" description="Step이나 표를 찾아 엽니다">
        <Command>
        <CommandInput placeholder="Step이나 표 이름" />
        <CommandList>
          <CommandEmpty>일치하는 항목이 없습니다</CommandEmpty>
          {!!steps.length && <CommandGroup heading="단계">
            {steps.map((s, i) => <CommandItem key={s.id} value={`${stepLabel(i)} step ${i + 1}`} onSelect={() => { setStepId(s.id); setPalette(false); }}>
              <span className="step-dot">{i + 1}</span>{stepLabel(i)}<CommandShortcut>{s.code_location ? `L${s.code_location.start}–${s.code_location.end}` : ""}</CommandShortcut>
            </CommandItem>)}
          </CommandGroup>}
          {!!tables.length && <CommandGroup heading="데이터">
            {tables.map((t) => <CommandItem key={t.id} value={`${t.label} 표 table`} onSelect={() => { setPanel(t.id); setPalette(false); }}>
              <Table2 />{t.label}<CommandShortcut>{t.table.rows.length}×{t.table.columns.length}</CommandShortcut>
            </CommandItem>)}
          </CommandGroup>}
          <CommandGroup heading="작업">
            <CommandItem onSelect={() => { setPalette(false); focusComposer(); }}><MessageSquare />수정 요청 쓰기<CommandShortcut>⌘I</CommandShortcut></CommandItem>
            <CommandItem onSelect={() => { setPalette(false); togglePanel(); }}><PanelBottom />아래 패널 열고 닫기<CommandShortcut>⌘J</CommandShortcut></CommandItem>
            <CommandItem onSelect={() => { setPalette(false); setSidebar((v) => !v); }}><PanelLeft />사이드바 열고 닫기<CommandShortcut>⌘B</CommandShortcut></CommandItem>
          </CommandGroup>
        </CommandList>
        </Command>
      </CommandDialog>
    </div>
  );
}

function EmptyEditor() {
  return <div className="flex flex-1 flex-col items-center justify-center gap-5 p-6 text-center">
    <div><p className="text-base font-medium">과제를 고르고 실행하세요</p><p className="mt-1 text-muted-foreground">위에서 과제를 고른 뒤 실행을 누르면 코드와 결과가 여기에 나타납니다.</p></div>
    <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {[["Step이나 표로 이동", "K"], ["사이드바", "B"], ["아래 패널", "J"], ["수정 요청 쓰기", "I"]].map(([label, key]) => <div key={key} className="contents">
        <dt className="text-right">{label}</dt><dd><KbdGroup><Kbd>⌘</Kbd><Kbd>{key}</Kbd></KbdGroup></dd>
      </div>)}
    </dl>
  </div>;
}

function ChatIntro({ inSitu }: { inSitu: boolean }) {
  const steps: [string, ReactNode][] = [
    ["확인", inSitu ? "표에서 색이 있는 셀을 눌러 어떤 변환이 일어났는지 봅니다." : "Step별 코드와 결과 표를 함께 봅니다."],
    ["요청", "고칠 내용을 문장으로 적어 보냅니다."],
    ["검토", "바로 바뀌지 않습니다. 수정안의 코드와 결과를 먼저 보고 적용할지 정합니다."],
  ];
  return <ol className="mt-1 space-y-3">{steps.map(([label, text], i) => <li key={label} className="flex gap-2.5">
    <span className="step-dot">{i + 1}</span><div><p className="font-medium">{label}</p><p className="text-xs leading-relaxed text-muted-foreground">{text}</p></div>
  </li>)}</ol>;
}

function ChatMessage({ message, waiting }: { message: Message; waiting?: boolean }) {
  return <>
    <div className="bubble-user">{message.request}</div>
    <div className={`flex gap-2 text-xs leading-relaxed ${message.failed ? "text-destructive" : waiting ? "text-amber-800" : "text-muted-foreground"}`}>
      {message.failed ? <CircleAlert className="mt-0.5 size-3.5 shrink-0" /> : waiting ? <ChevronLeft className="mt-0.5 size-3.5 shrink-0" /> : <Check className="mt-0.5 size-3.5 shrink-0 text-primary" />}
      <span>{message.response}</span>
    </div>
  </>;
}
