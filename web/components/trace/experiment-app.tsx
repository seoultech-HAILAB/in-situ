"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { TraceApp } from "./trace-app";
import { api, type Session } from "@/lib/trace";
import { connectStudy, flushStudy, logStudy, observeStudy, studyContext } from "@/lib/study-telemetry";
import { ParticipantTaskGuide, TASK_GUIDE_VERSION } from "./participant-task-guide";

type State = {
  id: string; token?: string; participant_id: string; condition: "in-situ" | "ex";
  phase: "tutorial" | "ready" | "preparing" | "task" | "break" | "complete";
  task_index: number; session_id: string | null; deadline: number | null; server_now: number;
  tasks: { id: string; title: string; description: string }[];
  tutorial_task: { id: string; title: string; description: string };
  protocol_version: string; current_protocol_version: string; previous_experiment_id?: string;
};

const clock = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

export function ExperimentApp({ condition }: { condition: "in-situ" | "ex" }) {
  const [research, setResearch] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [confirmFinish, setConfirmFinish] = useState(false);
  const [tutorialGuideAcceptedFor, setTutorialGuideAcceptedFor] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now() / 1000);
  const offset = useRef(0);
  const inFlight = useRef(false);
  const live = useRef(true);
  const latest = useRef<State | null>(null);
  const key = `trace-experiment:${condition}`;

  function accept(next: State) {
    offset.current = next.server_now - Date.now() / 1000;
    latest.current = next;
    studyContext({ experiment_id: next.id, participant_id: next.participant_id,
      phase: next.phase, task_index: next.task_index, task_number: next.phase === "tutorial" ? null : next.task_index + 1,
      task_id: next.phase === "tutorial" ? next.tutorial_task.id : next.tasks[next.task_index]?.id, session_id: next.session_id, condition });
    setNow(Date.now() / 1000 + offset.current);
    setState(next);
  }

  async function action(name: string, initial?: State) {
    const current = initial ?? latest.current;
    if (!current) throw new Error("실험을 불러오는 중입니다.");
    const next = await api<State>(`/experiments/${current.id}/action`, { action: name, expected_phase: current.phase, expected_index: current.task_index });
    if (live.current) accept(next);
    return next;
  }

  async function loadWorkspace(next: State) {
    if (!next.session_id) return;
    const loaded = await api<Session>(`/sessions/${next.session_id}`);
    if (loaded.status !== "ready") throw new Error("과제를 준비하지 못했습니다. 다시 시도하세요.");
    if (loaded.run?.explanation_status !== "ready") throw new Error("자연어 설명을 준비하지 못했습니다. 서버 API 연결을 확인한 뒤 다시 시도하세요.");
    if (live.current) setSession(loaded);
  }

  useEffect(() => {
    live.current = true;
    if (new URLSearchParams(location.search).get("research") === "1") { setResearch(true); setBusy(false); return; }
    let stop: (() => void) | undefined;
    void (async () => {
      let saved: { id: string; token: string } | null = null;
      try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch { /* A new browser enrolls below. */ }
      if (!saved?.id || !saved.token) saved=null;
      let next: State | undefined;
      if (saved?.id && saved.token) {
        await connectStudy(saved);
        // Never silently replace a participant when the server is unreachable.
        next = await api<State>(`/experiments/${saved.id}`);
      }
      if (!next || next.protocol_version!==next.current_protocol_version) {
        const previous = saved;
        if (previous) localStorage.setItem(`trace-experiment-history:${condition}:${previous.id}`,JSON.stringify(previous));
        next = await api<State>("/experiments", { condition, environment: {
          user_agent: navigator.userAgent, language: navigator.language, languages: navigator.languages,
          screen: { width: screen.width, height: screen.height, color_depth: screen.colorDepth },
          viewport: { width: innerWidth, height: innerHeight, pixel_ratio: devicePixelRatio },
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, touch_points: navigator.maxTouchPoints,
          hardware_concurrency: navigator.hardwareConcurrency,
        }, previous_experiment_id: previous?.id });
        saved = { id: next.id, token: next.token! };
        localStorage.setItem(key, JSON.stringify(saved));
        await connectStudy(saved);
      }
      if (!live.current) return;
      accept(next);
      stop = observeStudy();
      await action("resume", next);
      if (next.phase === "tutorial") next = await action("prepare_tutorial", next);
      if (["tutorial", "task", "preparing"].includes(next.phase)) await loadWorkspace(next);
    })().catch(e => live.current && setError((e as Error).message)).finally(() => live.current && setBusy(false));
    return () => { live.current = false; stop?.(); };
  }, []);

  useEffect(() => {
    if (research) return;
    const timer = setInterval(() => setNow(Date.now() / 1000 + offset.current), 250);
    const poll = async () => {
      const current = latest.current;
      if (!current || inFlight.current) return;
      try { const next = await api<State>(`/experiments/${current.id}`); if (live.current) accept(next); }
      catch { /* Keep the server-based deadline; reconnect does not reset it. */ }
    };
    const interval = setInterval(() => void poll(), 3000);
    const visible = () => { if (!document.hidden) void poll(); };
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("online", poll);
    return () => { clearInterval(timer); clearInterval(interval); document.removeEventListener("visibilitychange", visible); window.removeEventListener("online", poll); };
  }, [research]);

  async function perform(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try { await work(); } catch (e) { setError((e as Error).message); }
    finally { inFlight.current = false; if (live.current) setBusy(false); }
  }

  async function startTask() {
    let next = latest.current!;
    if (next.phase === "break") next = await action("next", next);
    if (next.phase !== "preparing") next = await action("prepare", next);
    setSession(null);
    await loadWorkspace(next);
  }

  const hasWorkspace = !!state && session?.id === state.session_id;
  const showStart = state?.phase === "preparing" && hasWorkspace && !busy;
  const showTutorialGuide = state?.phase === "tutorial" && hasWorkspace && !busy && tutorialGuideAcceptedFor !== state.id;
  useEffect(() => {
    if (!state?.id) return;
    try { if (localStorage.getItem(`trace-tutorial-guide:${state.id}`) === TASK_GUIDE_VERSION) setTutorialGuideAcceptedFor(state.id); }
    catch { /* The guide can still be acknowledged for the current page. */ }
  }, [state?.id]);
  useEffect(() => {
    if (showStart) logStudy("task.start_prompt", { task_number: state!.task_index + 1 });
  }, [showStart, state?.task_index]);
  useEffect(() => { if (state?.phase !== "task") setConfirmFinish(false); }, [state?.phase]);

  function cancelFinish() {
    logStudy("task.finish_cancelled");
    setConfirmFinish(false);
  }

  if (research) return <TraceApp condition={condition} />;
  const remaining = state?.deadline ? Math.max(0, Math.ceil(state.deadline - now)) : null;
  const active = state && ["tutorial", "preparing", "task"].includes(state.phase) && hasWorkspace && (state.phase !== "task" || remaining !== 0);
  const instructions = state?.phase === "tutorial" ? state.tutorial_task : state?.tasks[state.task_index];
  const toolbar = <>
    <strong className="study-task-number">{state?.phase === "tutorial" ? "Tutorial" : `Task ${(state?.task_index ?? 0) + 1}`}</strong>
    <span className={`study-timer ${remaining !== null && remaining <= 60 ? "study-timer-urgent" : ""}`} role="timer" aria-label="남은 시간">{state?.phase === "tutorial" ? "연습 · 시간 제한 없음" : clock(remaining ?? 900)}</span>
    <div className="toolbar-spacer" />
    {state?.phase === "task" && <button className="study-button secondary" disabled={busy} onClick={() => { logStudy("task.finish_prompt"); setConfirmFinish(true); }}>과제 종료</button>}
  </>;

  return <div className="experiment-shell">
    {state?.phase === "tutorial" && <aside className="study-tutorial" aria-label="튜토리얼 안내">
      <div><strong>{state.tutorial_task.title}</strong><p>① Input으로 학생 명부·행사 기록 확인 → ② Step을 눌러 코드와 결과 비교 → ③ {condition === "in-situ" ? "초록·노랑·빨강 영역을 눌러 개별 설명과 코드 확인" : "아래 설명 영역에서 바뀐 열과 개별 코드 확인"} → ④ 채팅에 수정 요청 → 후보 Step과 비교 후 Approve 또는 Deny</p>
        <p>연습: Step 1에서 “행사 유형이 비어 있어도 명부와 연결되는 학생의 행사 기록은 포함해줘”라고 요청해 보세요. 본실험은 3개 과제, 각 15분이며 과제 사이에 1분간 쉬거나 바로 다음 과제를 시작할 수 있습니다. 앱 안의 입력·조작·화면 이동과 실행 기록이 수집됩니다.</p></div>
      <button className="study-button" disabled={busy || !session} onClick={() => void perform(startTask)}>본실험 시작</button>
    </aside>}
    {error && <div className="study-error" role="alert">{error}<button onClick={() => location.reload()}>다시 연결</button></div>}
    {active && !busy && session ? <TraceApp key={session.id} condition={condition} managed={{ initialSession: session, toolbar }} /> :
      <main className="study-stage">
        {busy || !state || state.phase === "preparing" ? <><h1>준비 중</h1><p>코드 실행 결과와 설명을 불러옵니다. 이 시간은 과제 제한 시간에 포함되지 않습니다.</p></> :
          state.phase === "break" ? <><h1>잠시 쉬어가세요</h1><p>Task {state.task_index + 1}이 끝났습니다. 1분간 쉬거나 바로 다음 과제를 시작할 수 있습니다.</p><div className="study-break-clock" role="timer" aria-label="남은 휴식 시간">{clock(remaining ?? 60)}</div><button className="study-button" disabled={busy} onClick={() => void perform(startTask)}>Task {state.task_index + 2} 시작</button></> :
          state.phase === "complete" ? <><h1>실험이 완료되었습니다</h1><p>참여해 주셔서 감사합니다. 연구자에게 완료를 알려주세요.</p><small>참가자 {state.participant_id}</small></> :
            state.phase === "ready" ? <><h1>Task {state.task_index + 1}</h1><button className="study-button" onClick={() => void perform(startTask)}>과제 시작</button></> :
              <><h1>과제 시간이 종료되었습니다</h1><p>다음 화면으로 이동 중입니다.</p></>}
      </main>}
    {active && !busy && instructions && <details className="study-task-instructions" onToggle={event => logStudy(event.currentTarget.open ? "instructions.open" : "instructions.close", { task_id: instructions.id, placement: "workspace", guide_version: TASK_GUIDE_VERSION })}>
      <summary>{state?.phase === "tutorial" ? "튜토리얼 과제 안내" : "과제 안내"}</summary><div><ParticipantTaskGuide taskId={instructions.id} /></div>
    </details>}
    {showTutorialGuide && state && <StartGuideDialog key={`tutorial:${state.id}`} title="튜토리얼 시작" taskId={state.tutorial_task.id} timed={false} onStart={() => {
      try { localStorage.setItem(`trace-tutorial-guide:${state.id}`, TASK_GUIDE_VERSION); } catch { /* Keep the current acknowledgement in memory. */ }
      logStudy("tutorial.instructions_confirmed", { task_id: state.tutorial_task.id, guide_version: TASK_GUIDE_VERSION });
      setTutorialGuideAcceptedFor(state.id);
    }} />}
    {showStart && state && <StartGuideDialog key={`task:${state.session_id}`} title={`Task ${state.task_index + 1} 시작`} taskId={state.tasks[state.task_index].id} timed onStart={() => void perform(async () => {
      logStudy("task.start_confirmed", { task_id: state.tasks[state.task_index].id, guide_version: TASK_GUIDE_VERSION }); await action("begin");
    })} />}
    {confirmFinish && state?.phase === "task" && !busy && <StudyDialog title="과제를 종료하시겠습니까?" onCancel={cancelFinish}>
      <p>종료하면 현재까지 승인한 결과가 저장되고 이 과제로 돌아올 수 없습니다.</p>
      <div className="study-dialog-actions"><button className="study-button secondary" data-initial-focus onClick={cancelFinish}>취소</button><button className="study-button" onClick={() => void perform(async () => {
        logStudy("task.finish_confirmed"); await action("finish"); setConfirmFinish(false); await flushStudy();
      })}>확인</button></div>
    </StudyDialog>}
  </div>;
}

function StartGuideDialog({ title, taskId, timed, onStart }: { title: string; taskId: string; timed: boolean; onStart: () => void }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    logStudy("instructions.open", { task_id: taskId, placement: "start", guide_version: TASK_GUIDE_VERSION });
    return () => logStudy("instructions.close", { task_id: taskId, placement: "start", guide_version: TASK_GUIDE_VERSION });
  }, [taskId]);
  return <StudyDialog title={title} className="study-guide-dialog">
    <div className="study-guide-scroll" role="region" aria-label="시작 전 과제 안내" tabIndex={0} data-initial-focus>
      <ParticipantTaskGuide taskId={taskId} onReady={setReady} />
    </div>
    <div className="study-guide-footer">
      <p>{timed ? "시작을 누르면 15분 타이머가 작동합니다. 안내를 읽는 동안에는 시간이 흐르지 않습니다." : "튜토리얼은 시간 제한 없이 연습할 수 있습니다."}</p>
      <button className="study-button" disabled={!ready} onClick={onStart}>{timed ? "시작" : "튜토리얼 시작"}</button>
    </div>
  </StudyDialog>;
}

function StudyDialog({ title, children, onCancel, className = "" }: { title: string; children: ReactNode; onCancel?: () => void; className?: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    element.querySelector<HTMLElement>("[data-initial-focus]")?.focus();
    return () => element.close();
  }, []);
  return <dialog ref={dialog} className={`study-dialog ${className}`} aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onCancel?.(); }}>
    <h2 id={titleId}>{title}</h2>{children}
  </dialog>;
}
