"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, type LogEvent, type SessionRow } from "@/lib/trace";

export const EVENT_LABEL: Record<string, string> = {
  input_registered: "Input 등록",
  target_registered: "Target 등록",
  review_started: "검수 시작",
  step_selected: "단계 이동",
  cell_selected: "셀 선택",
  row_selected: "행 선택",
  column_selected: "열 선택",
  review_target_selected: "대상 선택",
  lineage_viewed: "출처 강조",
  review_comment_opened: "수정 요청 시작",
  explanation_viewed: "규칙 열람",
  evidence_viewed: "근거 열람",
  code_viewed: "코드 열람",
  review_note_saved: "메모 저장",
  review_mark_set: "확인 표시",
  review_summary_opened: "검수 기록 열기",
  revision_requested: "수정 요청",
  revision_completed: "수정 코드 생성",
  revision_execution_started: "수정 실행 시작",
  revision_execution_completed: "수정 실행 완료",
  revision_preview_ready: "미리보기 생성",
  revision_preview_applied: "미리보기 적용",
  revision_preview_discarded: "미리보기 취소",
  revision_failed: "수정 실패",
  revision_execution_failed: "수정 실행 실패",
  step_explanations_ready: "단계 설명 준비",
  execution_completed: "초기 실행 완료",
  study_task_started: "과제 시작",
  undo: "되돌리기",
  review_resumed: "검수 재개",
  final_confirmed: "확정",
  initial_step_judgment_saved: "처음 결과 판단 저장",
};

const HEAVY = new Set(["output", "proposal", "candidate_code", "code", "table", "assumptions"]);

/** One line of the most useful payload fields; large tables and code are left out. */
function brief(e: LogEvent): string {
  const d = e.data || {};
  if (typeof d.request === "string") return d.request;
  if (typeof d.note === "string") return `메모: ${d.note}`;
  const target = d.target as { kind?: string; column?: string; row_id?: string; step_id?: string } | undefined;
  if (target) return [target.kind, target.column, target.row_id].filter(Boolean).join(" ");
  const rest = Object.fromEntries(Object.entries(d).filter(([k]) => !HEAVY.has(k)));
  const text = JSON.stringify(rest);
  return text === "{}" ? "" : text.length > 160 ? text.slice(0, 160) + "…" : text;
}

const time = (iso: string) => {
  const d = new Date(iso);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
};

/** Live event log of one session, polled every two seconds while open. */
export function SessionLog({ session, live, onClose }: { session: SessionRow; live: boolean; onClose: () => void }) {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const last = useRef<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let stop = false;
    last.current = null;
    setEvents([]);
    const pull = async () => {
      try {
        const q = last.current ? `?after=${encodeURIComponent(last.current)}` : "";
        const r = await api<{ events: LogEvent[] }>(`/admin/sessions/${session.session_id}/events${q}`);
        if (stop || !r.events.length) return;
        last.current = r.events.at(-1)!.id;
        setEvents((prev) => [...prev, ...r.events]);
      } catch {
        /* the next poll retries */
      }
    };
    void pull();
    const timer = live ? setInterval(pull, 2000) : undefined;
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [session.session_id, live]);

  // Braces matter: newer browsers return a Promise from scrollIntoView, which React would treat as a cleanup.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [events.length]);

  const q = filter.trim().toLowerCase();
  const shown = q ? events.filter((e) => `${e.event} ${EVENT_LABEL[e.event] || ""} ${brief(e)}`.toLowerCase().includes(q)) : events;

  return (
    <aside aria-label="세션 로그" className="flex h-full flex-col border-l bg-card">
      <div className="flex items-start gap-2 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{session.title}</p>
          <p className="text-xs text-muted-foreground">
            {session.participant_label || "참가자 없음"}, {session.condition === "ex" ? "Ex-situ" : "In-situ"}, 이벤트 {events.length}개
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="로그 닫기" onClick={onClose}>
          <X />
        </Button>
      </div>
      <div className="border-b px-4 py-2">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="이벤트 검색"
          aria-label="이벤트 검색"
          className="h-8 w-full rounded-md border bg-background px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />
      </div>
      <ol className="min-h-0 flex-1 overflow-y-auto py-1 text-sm">
        {shown.map((e) => (
          <li key={e.id} className="border-b border-border/60 last:border-0">
            <button type="button" onClick={() => setOpen(open === e.id ? null : e.id)} className="flex w-full gap-3 px-4 py-1.5 text-left hover:bg-muted/60">
              <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{time(e.timestamp)}</span>
              <span className="min-w-0 flex-1">
                <span className="font-medium">{EVENT_LABEL[e.event] || e.event}</span>
                {brief(e) && <span className="ml-2 break-all text-muted-foreground">{brief(e)}</span>}
              </span>
            </button>
            {open === e.id && (
              <pre className="mx-4 mb-2 max-h-64 overflow-auto rounded-md bg-muted p-2 font-mono text-xs whitespace-pre-wrap">{JSON.stringify({ event: e.event, ...e.data }, null, 2)}</pre>
            )}
          </li>
        ))}
        {!shown.length && <li className="px-4 py-6 text-center text-muted-foreground">이벤트가 없습니다</li>}
        <div ref={bottom} />
      </ol>
    </aside>
  );
}
