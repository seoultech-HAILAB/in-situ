"use client";

import { LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { taskLabel, type Condition, type TaskInput, type TaskSummary } from "@/lib/trace";
import { DataTable } from "./data-table";

const conditions: { id: Condition; name: string; detail: string }[] = [
  { id: "ex", name: "Ex-situ", detail: "단계 설명, 코드, 결과 표" },
  { id: "in-situ", name: "In-situ", detail: "단계 설명, 변환 전후 표" },
];

/** Experimenter-facing setup. Participants start from the review screen. */
export function TaskStart({
  tasks,
  loading,
  task,
  condition,
  busy,
  onTask,
  onCondition,
  onStart,
  onResume,
}: {
  tasks: TaskSummary[];
  loading: boolean;
  task: TaskInput | null;
  condition: Condition;
  busy: boolean;
  onTask: (id: string) => void;
  onCondition: (c: Condition) => void;
  onStart: () => void;
  onResume?: () => void;
}) {
  const items = Object.fromEntries(tasks.map((t) => [t.id, taskLabel(t)]));
  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-10">
      <div className="flex items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">검수 준비</h1>
        {onResume && (
          <Button variant="ghost" onClick={onResume} disabled={busy}>
            진행 중인 검수로 돌아가기
          </Button>
        )}
      </div>

      <div className="mt-8 grid gap-8 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-2">
          <Label htmlFor="task">과제</Label>
          <Select items={items} value={task?.id ?? null} disabled={busy || loading} onValueChange={(v) => v && onTask(String(v))}>
            <SelectTrigger id="task" className="w-full">
              <SelectValue placeholder={loading ? "불러오는 중" : "과제를 고르세요"} />
            </SelectTrigger>
            <SelectContent>
              {tasks.map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {taskLabel(t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!loading && !tasks.length && <p className="text-sm text-muted-foreground">등록된 과제가 없습니다.</p>}
        </div>

        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">조건</legend>
          <RadioGroup value={condition} onValueChange={(v) => onCondition(v as Condition)} className="grid gap-2 sm:grid-cols-2" disabled={busy}>
            {conditions.map((c) => (
              <Label
                key={c.id}
                className="flex cursor-pointer items-start gap-3 rounded-md border bg-card p-3 font-normal has-data-checked:border-primary has-data-checked:bg-accent"
              >
                <RadioGroupItem value={c.id} className="mt-0.5" />
                <span>
                  <span className="block font-medium">{c.name}</span>
                  <span className="block text-sm text-muted-foreground">{c.detail}</span>
                </span>
              </Label>
            ))}
          </RadioGroup>
        </fieldset>
      </div>

      {task && (
        <div className="mt-10 grid gap-6 lg:grid-cols-2">
          <section className="min-w-0 space-y-2">
            <h2 className="text-sm font-medium">
              Input <span className="font-normal text-muted-foreground">{task.input.stats.rows}행</span>
            </h2>
            <DataTable data={task.input} />
            {Object.entries(task.sources).map(([name, table]) => (
              <div key={name} className="space-y-2 pt-2">
                <h3 className="text-sm font-medium">
                  {name} <span className="font-normal text-muted-foreground">{table.stats.rows}행</span>
                </h3>
                <DataTable data={table} />
              </div>
            ))}
          </section>
          <section className="min-w-0 space-y-2">
            <h2 className="text-sm font-medium">
              Target <span className="font-normal text-muted-foreground">{task.target.stats.rows}행</span>
            </h2>
            <DataTable data={task.target} />
          </section>
        </div>
      )}

      <div className="mt-10 flex justify-end">
        <Button size="lg" disabled={busy || !task} onClick={onStart} className="min-w-32">
          {busy && <LoaderCircle className="animate-spin" />}
          검수 시작
        </Button>
      </div>
    </main>
  );
}
