import { useEffect, useMemo, useRef } from "react";
import type { Stage, Table } from "@/lib/trace";
import { highlight } from "./python-code";
import { workspaceDiff } from "./workspace-diff";

type Line = { kind: " " | "+" | "-"; text: string; a?: number; b?: number };

// ponytail: O(n·m) LCS over lines; fine for step-sized scripts, switch to Myers if files reach thousands of lines.
export function lineDiff(before: string, after: string): Line[] {
  const x = before.split(/\r\n|\r|\n/), y = after.split(/\r\n|\r|\n/);
  const L = Array.from({ length: x.length + 1 }, () => new Uint32Array(y.length + 1));
  for (let i = x.length - 1; i >= 0; i--)
    for (let j = y.length - 1; j >= 0; j--) L[i][j] = x[i] === y[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: Line[] = [];
  let i = 0, j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) out.push({ kind: " ", text: x[i], a: ++i, b: ++j });
    else if (j < y.length && (i >= x.length || L[i][j + 1] >= L[i + 1][j])) out.push({ kind: "+", text: y[j], b: ++j });
    else out.push({ kind: "-", text: x[i], a: ++i });
  }
  return out;
}

/** Inline diff editor: both line-number gutters, removed lines above their replacements. */
export function CodeDiff({ before, after }: { before: string; after: string }) {
  const lines = useMemo(() => lineDiff(before, after), [before, after]);
  const first = useRef<HTMLDivElement>(null);
  useEffect(() => { first.current?.scrollIntoView({ block: "center" }); }, [lines]);
  // Land on the first change that is code, not a dropped comment or blank line.
  const changed = (line: Line) => line.kind !== " ";
  const firstChange = Math.max(lines.findIndex((line) => changed(line) && line.text.trim() && !line.text.trim().startsWith("#")), lines.findIndex(changed));
  return <div className="code-diff" role="region" aria-label="코드 변경 비교">
    {lines.map((line, index) => <div key={index} ref={index === firstChange ? first : undefined} className="diff-line" data-kind={line.kind === "+" ? "added" : line.kind === "-" ? "removed" : undefined}>
      <span className="diff-gutter">{line.a ?? ""}</span><span className="diff-gutter">{line.b ?? ""}</span>
      <span className="diff-sign" aria-label={line.kind === "+" ? "추가된 줄" : line.kind === "-" ? "삭제된 줄" : undefined}>{line.kind === " " ? "" : line.kind}</span>
      <code>{highlight(line.text)}</code>
    </div>)}
  </div>;
}

/** The candidate step dressed as a transformation of the current result, so the table encodings show run-to-run changes. */
export function asRunChange(current: Table, candidate: Stage): Stage {
  return { ...candidate, input: current, inputs: undefined, operations: undefined, transformations: undefined, trace_level: "detailed", kind: "derive" };
}

export function changeSummary(current: Table, candidate: Stage): string {
  const next = candidate.table;
  const diff = workspaceDiff(asRunChange(current, candidate));
  const cells = diff.rows.reduce((n, row) => n + Object.values(row.cells).filter((cell) => cell.kind === "changed").length, 0);
  const added = diff.columns.filter((c) => c.kind === "added").map((c) => c.name);
  const parts = [current.rows.length === next.rows.length ? `${next.rows.length}행 그대로` : `${current.rows.length}행에서 ${next.rows.length}행으로`];
  if (added.length) parts.push(`새 열 ${added.join(", ")}`);
  if (diff.removedColumns) parts.push(`빠지는 열 ${diff.removedColumns}개`);
  parts.push(cells ? `바뀌는 셀 ${cells}개` : "값이 바뀌는 셀 없음");
  return parts.join(", ");
}
