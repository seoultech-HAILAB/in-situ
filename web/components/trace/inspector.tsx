"use client";

import { useState, type ReactNode } from "react";
import { Check, ChevronRight, MessageSquareText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { fmt, type Ref, type ReviewTarget, type Stage, type Table } from "@/lib/trace";
import { CodeView } from "./code-view";
import { ColumnOriginDetails } from "./column-origin";
import { VIEW_LABEL, type TargetRecord } from "./history";

type ViewEvent = keyof typeof VIEW_LABEL;

/**
 * Detail card for the selected data (in-situ). Rule, input evidence and code are
 * opened on demand; each opening is recorded against this execution version.
 */
export function Inspector(p: {
  target: ReviewTarget | null;
  title: string;
  preview: string;
  step: Stage;
  stage?: Stage;
  refs: Ref[];
  keyRefs: Ref[];
  record?: TargetRecord;
  runLabel: string;
  locked: boolean;
  onView: (event: ViewEvent) => void;
  onNote: (note: string) => void;
  onMark: (checked: boolean) => void;
  onAsk: () => void;
}) {
  if (!p.target) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-muted-foreground">
        <MessageSquareText className="size-5" />
        표에서 셀, 행, 열을 선택하세요
      </div>
    );
  }
  return <Details key={JSON.stringify(p.target)} {...p} target={p.target} />;
}

function Details(p: Parameters<typeof Inspector>[0] & { target: ReviewTarget }) {
  const { target, step, record } = p;
  const stage = p.stage || step;
  const [note, setNote] = useState(record?.note || "");
  const column = target.column;
  const input = target.table_role === "input";

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-1 border-b px-4 py-3">
        <p className="font-medium leading-snug">{p.title}</p>
        {p.preview && <p className="line-clamp-3 text-xs whitespace-pre-line text-muted-foreground">{p.preview}</p>}
        <p className="text-xs text-muted-foreground">{p.runLabel}</p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <Section label="규칙" seen={record?.viewed.has("explanation_viewed")} onOpen={() => p.onView("explanation_viewed")}>
          <Rule target={target} stage={stage} column={column} />
        </Section>
        <Section label="입력 근거" seen={record?.viewed.has("evidence_viewed")} onOpen={() => p.onView("evidence_viewed")}>
          <Evidence target={target} stage={stage} refs={p.refs} keyRefs={p.keyRefs} />
        </Section>
        <Section label="코드" seen={record?.viewed.has("code_viewed")} onOpen={() => p.onView("code_viewed")}>
          <LinkedCode step={step} target={target} input={input} />
        </Section>

        <div className="space-y-3 border-b px-4 py-3">
          <p className="text-xs font-medium text-muted-foreground">이 결과에서 남긴 기록</p>
          <p className="text-sm">
            {record?.viewed.size ? `열어 본 항목: ${[...record.viewed].map((v) => VIEW_LABEL[v]).join(", ")}` : "열어 본 항목이 없습니다"}
          </p>
          <Textarea
            rows={2}
            value={note}
            disabled={p.locked}
            placeholder="메모"
            onChange={(e) => setNote(e.target.value)}
            className="min-h-16 text-sm"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" disabled={p.locked || note.trim() === (record?.note || "")} onClick={() => p.onNote(note.trim())}>
              메모 저장
            </Button>
            <Button
              size="sm"
              variant={record?.checked ? "secondary" : "outline"}
              aria-pressed={!!record?.checked}
              disabled={p.locked}
              onClick={() => p.onMark(!record?.checked)}
            >
              <Check /> {record?.checked ? "확인 표시됨" : "확인 표시"}
            </Button>
          </div>
        </div>
      </div>

      <div className="border-t p-3">
        <Button className="w-full" variant="outline" disabled={p.locked} onClick={p.onAsk}>
          이 선택으로 수정 요청
        </Button>
      </div>
    </div>
  );
}

function Section({ label, seen, onOpen, children }: { label: string; seen?: boolean; onOpen: () => void; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => {
          if (!open) onOpen();
          setOpen(!open);
        }}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm font-medium hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset"
      >
        <ChevronRight className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-90")} />
        {label}
        {seen && (
          <span className="ml-auto text-xs font-normal text-muted-foreground" title="이 결과에서 열어 본 항목">
            열어 봄
          </span>
        )}
      </button>
      {open && <div className="px-4 pb-3 text-sm">{children}</div>}
    </div>
  );
}

function Rule({ target, stage, column }: { target: ReviewTarget; stage: Stage; column?: string }) {
  if (column) return <ColumnOriginDetails stage={stage} column={column} />;
  const decision = target.row_id ? stage.params.decisions?.[target.row_id] : undefined;
  if (decision?.tests.length)
    return (
      <ul className="space-y-1">
        {decision.tests.map((t, i) => (
          <li key={i}>
            {t.label} <span className="text-muted-foreground">{t.passed == null ? "" : t.passed ? "충족" : "미충족"}</span>
          </li>
        ))}
      </ul>
    );
  if (target.columns?.length === 1) return <ColumnOriginDetails stage={stage} column={target.columns[0]} />;
  return <p className="text-muted-foreground">이 선택에 연결된 규칙을 확인하지 못했습니다. 열이나 셀을 선택하면 열 단위 규칙을 볼 수 있습니다.</p>;
}

function tablesOf(stage: Stage): { name: string; table: Table }[] {
  const out: { name: string; table: Table }[] = [];
  if (stage.inputs?.length) stage.inputs.forEach((i, n) => out.push({ name: i.variable || `입력 ${n + 1}`, table: i.table }));
  else if (stage.input) out.push({ name: "변환 전 표", table: stage.input });
  return out;
}

function lookup(stage: Stage, ref: Ref) {
  for (const { name, table } of tablesOf(stage)) {
    const i = table.rows.findIndex((r) => r.id === ref.row_id);
    if (i >= 0 && ref.column in table.rows[i].values) return { name, row: i + 1, value: table.rows[i].values[ref.column] };
  }
  return null;
}

function RefList({ stage, refs }: { stage: Stage; refs: Ref[] }) {
  const items = refs.slice(0, 8).map((r) => ({ r, hit: lookup(stage, r) }));
  return (
    <ul className="space-y-1">
      {items.map(({ r, hit }, i) => (
        <li key={i} className="flex gap-2">
          <span className="shrink-0 text-muted-foreground">{hit ? `${hit.name} ${hit.row}행` : "이전 표"}</span>
          <span className="min-w-0 truncate">
            {r.column}: {hit ? fmt(hit.value) || "빈칸" : "값 확인 불가"}
          </span>
        </li>
      ))}
      {refs.length > 8 && <li className="text-muted-foreground">외 {refs.length - 8}개</li>}
    </ul>
  );
}

function Evidence({ target, stage, refs, keyRefs }: { target: ReviewTarget; stage: Stage; refs: Ref[]; keyRefs: Ref[] }) {
  const context = target.row_id && target.column ? stage.contexts?.[target.row_id]?.[target.column] : undefined;
  const rowSources = target.kind === "row" && target.row_id ? stage.row_sources[target.row_id] || [] : [];
  const parts: ReactNode[] = [];
  if (refs.length) parts.push(<div key="r" className="space-y-1"><p className="text-xs text-muted-foreground">이 값을 만든 입력 값</p><RefList stage={stage} refs={refs} /></div>);
  if (context)
    parts.push(
      <div key="g" className="space-y-1">
        <p className="text-xs text-muted-foreground">그룹 기준, 구성 행 {context.member_rows.length}개</p>
        <p>{Object.entries(context.group_keys).map(([k, v]) => `${k} = ${fmt(v) || "빈칸"}`).join(", ")}</p>
      </div>,
    );
  else if (keyRefs.length) parts.push(<div key="k" className="space-y-1"><p className="text-xs text-muted-foreground">연결에 쓴 키</p><RefList stage={stage} refs={keyRefs} /></div>);
  if (rowSources.length)
    parts.push(
      <p key="s">
        <span className="text-muted-foreground">이 행을 만든 입력 행 </span>
        {rowSources.length}개
      </p>,
    );
  if (!parts.length) return <p className="text-muted-foreground">이 선택의 입력 근거를 확인하지 못했습니다. 셀 하나를 선택하면 값별 근거를 볼 수 있습니다.</p>;
  return <div className="space-y-3">{parts}</div>;
}

/** Operations whose recorded effects touch the target; otherwise the whole step code. */
function linkedLines(step: Stage, target: ReviewTarget) {
  const column = target.column || (target.columns?.length === 1 ? target.columns[0] : undefined);
  const ops = (step.operations || []).filter((op) =>
    column
      ? op.changes?.added_columns.includes(column) || !!op.params.formulas?.[column] || !!op.params.aggregations?.[column]
      : target.kind === "row" || target.kind === "rows"
        ? !!op.changes?.rows
        : false,
  );
  // code_location counts lines of the full submitted script, which can differ from
  // the step's normalized code, so locate each statement by its text instead.
  const lines = step.code.split("\n").map((l) => l.trim());
  const ranges: { start: number; end: number }[] = [];
  for (const op of ops) {
    const own = op.code.split("\n");
    const at = lines.indexOf(own[0].trim());
    if (at >= 0 && own.length < lines.length) ranges.push({ start: at + 1, end: at + own.length });
  }
  return ranges;
}

function LinkedCode({ step, target, input }: { step: Stage; target: ReviewTarget; input: boolean }) {
  const ranges = input ? [] : linkedLines(step, target);
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">{ranges.length ? "이 선택과 연결된 줄을 표시했습니다" : "이 단계 전체 코드 (선택과 연결된 줄을 확인하지 못함)"}</p>
      <div className="max-h-72 overflow-auto rounded-md border bg-[#fbfbfc]">
        <CodeView code={step.code} highlight={ranges} />
      </div>
    </div>
  );
}
