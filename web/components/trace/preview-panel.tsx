"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { cellKey, reviewRun, stepTitle, type Preview, type Run, type Stage, type Table, type TableChanges } from "@/lib/trace";
import { CodeView } from "./code-view";
import { DataTable } from "./data-table";

/**
 * Run-to-run difference of one table. Cells are compared only when every new row
 * keeps an id from the current result; otherwise rows are not matched at all.
 */
export function runDelta(current: Table, next: Table): TableChanges {
  const before = new Map(current.rows.map((r) => [r.id, r]));
  const rowIdentity = next.rows.length > 0 && next.rows.every((r) => before.has(r.id));
  const common = next.columns.filter((c) => current.columns.includes(c));
  const changedCells = new Set<string>();
  const changedRows = new Set<string>();
  if (rowIdentity)
    for (const row of next.rows)
      for (const c of common)
        if (JSON.stringify(before.get(row.id)!.values[c]) !== JSON.stringify(row.values[c])) {
          changedCells.add(cellKey(row.id, c));
          changedRows.add(row.id);
        }
  const ids = new Set(next.rows.map((r) => r.id));
  return {
    addedColumns: next.columns.filter((c) => !current.columns.includes(c)),
    removedColumns: current.columns.filter((c) => !next.columns.includes(c)),
    retypedColumns: [],
    changedCells,
    changedRows,
    movedRows: new Set(),
    removedRows: rowIdentity ? current.rows.filter((r) => !ids.has(r.id)) : [],
    rowIdentity,
    rowsDelta: next.rows.length - current.rows.length,
    columnsReordered: false,
  };
}

function summary(current: Table, next: Table, d: TableChanges) {
  const parts = [current.rows.length === next.rows.length ? `${next.rows.length}행 그대로` : `${current.rows.length}행에서 ${next.rows.length}행으로`];
  if (d.addedColumns.length) parts.push(`새 열 ${d.addedColumns.join(", ")}`);
  if (d.removedColumns.length) parts.push(`빠지는 열 ${d.removedColumns.join(", ")}`);
  if (d.rowIdentity) parts.push(d.changedCells.size ? `바뀌는 셀 ${d.changedCells.size}개` : "값이 바뀌는 셀 없음");
  if (d.removedRows.length) parts.push(`빠지는 행 ${d.removedRows.length}개`);
  return parts.join(", ");
}

const reviewSteps = (run: Run) => reviewRun(run)?.stages.filter((s) => s.kind !== "input") ?? [];

export function PreviewPanel({
  preview,
  run,
  annotated,
  busy,
  onApply,
  onDiscard,
}: {
  preview: Preview;
  run: Run;
  annotated: boolean;
  busy: boolean;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const blocks = useMemo(() => {
    const now = reviewSteps(run);
    const next = reviewSteps(preview.run);
    const index = Math.max(0, now.findIndex((s) => s.id === preview.context?.step_id));
    const pairs: { label: string; now?: Stage; next?: Stage }[] = [
      { label: `${index + 1}단계 결과`, now: now[index], next: next.find((s) => s.id === now[index]?.id) || next[index] },
    ];
    if (index < now.length - 1) pairs.push({ label: "최종 결과", now: now.at(-1), next: next.at(-1) });
    return pairs;
  }, [run, preview]);

  return (
    <section aria-labelledby="preview-title" className="overflow-hidden rounded-xl border-2 border-foreground/70">
      <div className="flex flex-wrap items-center gap-3 border-b bg-panel-head px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 id="preview-title" className="text-sm font-semibold">
            수정 미리보기
          </h2>
          <p className="truncate text-sm text-muted-foreground">{preview.request}</p>
        </div>
        <Button variant="outline" size="sm" disabled={busy} onClick={onDiscard}>
          취소
        </Button>
        <Button size="sm" disabled={busy} onClick={onApply}>
          이대로 적용
        </Button>
      </div>
      <div className="space-y-5 p-4">
        {blocks.map(({ label, now, next }) =>
          now && next ? (
            <Block key={label} label={label} now={now} next={next} annotated={annotated} />
          ) : (
            <p key={label} className="text-sm text-muted-foreground">
              {label}: 수정 후 같은 단계를 찾지 못했습니다.
            </p>
          ),
        )}
      </div>
    </section>
  );
}

function Block({ label, now, next, annotated }: { label: string; now: Stage; next: Stage; annotated: boolean }) {
  const delta = useMemo(() => runDelta(now.table, next.table), [now, next]);
  return (
    <div className="space-y-2">
      <p className="text-sm">
        <span className="font-medium">{label}</span>{" "}
        <span className="text-muted-foreground">
          {next.nl_explanation?.title || stepTitle(next)}. {summary(now.table, next.table, delta)}
        </span>
      </p>
      {annotated ? (
        <DataTable data={next.table} stage={{ ...next, input: now.table }} annotated delta={delta} />
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">
          <div className="max-h-80 overflow-auto rounded-md border bg-[#fbfbfc]">
            <CodeView code={next.code} />
          </div>
          <DataTable data={next.table} stage={next} />
        </div>
      )}
    </div>
  );
}
