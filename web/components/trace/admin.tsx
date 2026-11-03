"use client";

import { useEffect, useState } from "react";
import { Copy, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { api, taskLabel, type Condition, type SessionRow, type TaskSummary } from "@/lib/trace";
import { EVENT_LABEL, SessionLog } from "./session-log";

/** "12초 전" style age; a session counts as active when its last event is under a minute old. */
function age(iso: string | null | undefined, now: number) {
  if (!iso) return { text: "", active: false };
  const sec = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  const text = sec < 60 ? `${sec}초 전` : sec < 3600 ? `${Math.floor(sec / 60)}분 전` : sec < 86400 ? `${Math.floor(sec / 3600)}시간 전` : `${Math.floor(sec / 86400)}일 전`;
  return { text, active: sec < 60 };
}

const conditionName = { ex: "Ex-situ", "in-situ": "In-situ" } as const;

/** Researcher page: make participant links per task and condition, and follow sessions. */
export function Admin() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [pid, setPid] = useState("");
  const [conditions, setConditions] = useState<Record<string, Condition>>({});
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [live, setLive] = useState(true);
  const [logId, setLogId] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const loadSessions = () =>
    api<{ sessions: SessionRow[] }>("/admin/sessions")
      .then((r) => {
        setSessions(r.sessions);
        setNow(Date.now());
        const ids = new Set(r.sessions.map((x) => x.session_id));
        setChecked((c) => new Set([...c].filter((id) => ids.has(id))));
      })
      .catch((e) => setError((e as Error).message));
  useEffect(() => {
    api<TaskSummary[]>("/woz-tasks")
      .then(setTasks)
      .catch((e) => setError((e as Error).message));
    void loadSessions();
  }, []);
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => void loadSessions(), 3000);
    return () => clearInterval(timer);
  }, [live]);

  const remove = async () => {
    const ids = [...checked];
    try {
      const r = await api<{ deleted: string[] }>("/admin/sessions/delete", { session_ids: ids });
      if (logId && r.deleted.includes(logId)) setLogId(null);
      setChecked(new Set());
      toast.success(`세션 ${r.deleted.length}개를 삭제했습니다`);
      await loadSessions();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const allChecked = sessions.length > 0 && checked.size === sessions.length;
  const logSession = sessions.find((x) => x.session_id === logId);

  const linkFor = (task: string, condition: Condition) => {
    const url = new URL("/", location.origin);
    url.searchParams.set("task", task);
    url.searchParams.set("condition", condition);
    if (pid.trim()) url.searchParams.set("pid", pid.trim());
    return url.toString();
  };
  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast.success("링크를 복사했습니다");
  };

  return (
    <div className="min-h-dvh bg-background">
      <header className="flex h-12 items-center gap-3 border-b px-4">
        <span className="font-semibold tracking-tight">TRACE</span>
        <span className="text-muted-foreground/60" aria-hidden>
          /
        </span>
        <span className="text-sm">관리자</span>
        <div className="ml-auto flex gap-1">
          <Button variant="ghost" size="sm" render={<a href="/?research=1" />}>
            연구자 검수 화면
          </Button>
          <Button variant="ghost" size="sm" render={<a href="/legacy?research=1" />}>
            기존 연구자 도구
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-10 px-6 py-8">
        {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}

        <section className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">참가자 링크</h1>
              <p className="text-sm text-muted-foreground">과제와 조건을 정하고 링크를 참가자에게 보냅니다. 같은 링크로 다시 들어오면 진행 중인 검수가 이어집니다.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pid">참가자 번호</Label>
              <input
                id="pid"
                value={pid}
                onChange={(e) => setPid(e.target.value)}
                placeholder="예: P01"
                className="h-8 w-40 rounded-md border bg-card px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              />
            </div>
          </div>
          <div className="overflow-hidden rounded-xl border">
            <table className="w-full text-sm">
              <thead className="bg-panel-head text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 font-medium">과제</th>
                  <th className="px-4 py-2 font-medium">조건</th>
                  <th className="px-4 py-2 font-medium">링크</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => {
                  const condition = conditions[t.id] || "in-situ";
                  const url = linkFor(t.id, condition);
                  return (
                    <tr key={t.id} className="border-t">
                      <td className="px-4 py-2.5">
                        <span className="block">{taskLabel(t)}</span>
                        <span className="text-xs text-muted-foreground">{t.id}</span>
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label={`${t.title} 조건`}>
                          {(["ex", "in-situ"] as const).map((c) => (
                            <button
                              key={c}
                              type="button"
                              aria-pressed={condition === c}
                              onClick={() => setConditions((m) => ({ ...m, [t.id]: c }))}
                              className={cn(
                                "rounded-md px-2.5 py-1 text-xs font-medium",
                                condition === c ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                              )}
                            >
                              {conditionName[c]}
                            </button>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-1">
                          <code className="min-w-0 flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{url.replace(location.origin, "")}</code>
                          <Button variant="ghost" size="icon-sm" aria-label="링크 복사" onClick={() => void copy(url)}>
                            <Copy />
                          </Button>
                          <Button variant="ghost" size="icon-sm" aria-label="새 탭에서 열기" render={<a href={url} target="_blank" rel="noreferrer" />}>
                            <ExternalLink />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="mr-auto text-xl font-semibold tracking-tight">
              검수 세션 <span className="text-base font-normal text-muted-foreground tabular-nums">{sessions.length}</span>
            </h2>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-4 accent-primary" checked={live} onChange={(e) => setLive(e.target.checked)} />
              실시간 갱신
            </label>
            <Button variant="outline" size="sm" onClick={() => void loadSessions()}>
              <RefreshCw /> 새로고침
            </Button>
            <AlertDialog>
              <AlertDialogTrigger render={<Button variant="destructive" size="sm" disabled={!checked.size} />}>
                <Trash2 /> 선택 삭제 {checked.size > 0 && checked.size}
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>세션 {checked.size}개를 삭제할까요?</AlertDialogTitle>
                  <AlertDialogDescription>
                    목록과 내보내기에서 빠집니다. 파일은 .local/deleted-sessions 폴더로 옮겨지며, 되살리려면 그 파일을 .local/sessions로 다시 옮기면 됩니다.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>취소</AlertDialogCancel>
                  <AlertDialogAction variant="destructive" onClick={() => void remove()}>
                    삭제
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full text-sm">
              <thead className="bg-panel-head text-left text-xs text-muted-foreground">
                <tr>
                  <th className="w-10 px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label="모두 선택"
                      className="size-4 accent-primary"
                      checked={allChecked}
                      onChange={() => setChecked(allChecked ? new Set() : new Set(sessions.map((x) => x.session_id)))}
                    />
                  </th>
                  {["시작", "참가자", "과제", "조건", "상태", "마지막 활동", "수정 실행/요청", "되돌리기", ""].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sessions.map((x) => {
                  const a = age(x.last_event_at, now);
                  return (
                    <tr key={x.session_id} className={cn("border-t", logId === x.session_id && "bg-accent")}>
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label={`${x.title} 세션 선택`}
                          className="size-4 accent-primary"
                          checked={checked.has(x.session_id)}
                          onChange={() =>
                            setChecked((c) => {
                              const next = new Set(c);
                              if (next.has(x.session_id)) next.delete(x.session_id);
                              else next.add(x.session_id);
                              return next;
                            })
                          }
                        />
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap tabular-nums">{new Date(x.started_at).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" })}</td>
                      <td className="px-3 py-2">{x.participant_label || <span className="text-muted-foreground">없음</span>}</td>
                      <td className="px-3 py-2">{x.title}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{conditionName[x.condition] || x.condition}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {x.confirmed ? "확정" : x.status === "generating" ? "수정 실행 중" : x.preview_pending ? "미리보기 확인 중" : x.status === "failed" ? "수정 실패" : "검수 중"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1.5">
                          {a.active && <span className="size-2 rounded-full bg-emerald-500" title="최근 1분 안에 활동" />}
                          <span className="tabular-nums">{a.text}</span>
                          <span className="text-muted-foreground">{x.last_event ? EVENT_LABEL[x.last_event] || x.last_event : ""}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2 tabular-nums">
                        {x.revision_executions}/{x.revision_requests}
                      </td>
                      <td className="px-3 py-2 tabular-nums">{x.undo_count}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <Button variant={logId === x.session_id ? "secondary" : "ghost"} size="sm" onClick={() => setLogId(logId === x.session_id ? null : x.session_id)}>
                          로그
                        </Button>
                        <Button variant="ghost" size="sm" render={<a href={`/?session=${x.session_id}&research=1`} target="_blank" rel="noreferrer" />}>
                          열기
                        </Button>
                        <Button variant="ghost" size="sm" render={<a href={`/api/sessions/${x.session_id}/export`} />}>
                          내보내기
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!sessions.length && <p className="px-4 py-6 text-center text-sm text-muted-foreground">아직 세션이 없습니다</p>}
          </div>
        </section>
      </main>
      {logSession && (
        <div className="fixed top-12 right-0 bottom-0 z-40 w-full max-w-md shadow-[-8px_0_24px_rgba(16,24,40,.08)]">
          <SessionLog session={logSession} live={live} onClose={() => setLogId(null)} />
        </div>
      )}
    </div>
  );
}
