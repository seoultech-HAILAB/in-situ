"use client";

import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from "react";
import { cn } from "@/lib/utils";
import {
  cellKey,
  fmt,
  groupBorder,
  groupColor,
  pointKey,
  selectedCells,
  useTableDrag,
  type Ref,
  type ReviewTarget,
  type Selection,
  type Stage,
  type Table,
  type TableChanges,
} from "@/lib/trace";
import { ColumnOrigin } from "./column-origin";
import type { Marks } from "./history";

const PREVIEW_ROWS = 5;

type Role = "input" | "output";
export type TableHandlers = {
  onCell?: (row: string, column: string, anchor: HTMLElement, additive: boolean) => void;
  onRow?: (row: string, anchor: HTMLElement, additive: boolean) => void;
  onColumn?: (column: string, anchor: HTMLElement, additive: boolean) => void;
  onRange?: (target: ReviewTarget, anchor: HTMLElement, final: boolean) => void;
};

/**
 * One table component for both conditions. `annotated` turns on the in-situ
 * encodings (changes, groups, provenance, selection); without it the table is a
 * plain result view.
 */
export function DataTable({
  data,
  stage,
  role = "output",
  inputRef,
  annotated = false,
  delta,
  inputDelta,
  groupRows,
  groupCells,
  refs = [],
  keyRefs = [],
  selection,
  picked: pickedTarget,
  disabled = false,
  handlers = {},
  marks,
}: {
  data: Table;
  stage?: Stage;
  role?: Role;
  inputRef?: string;
  annotated?: boolean;
  delta?: TableChanges | null;
  inputDelta?: TableChanges | null;
  groupRows?: Record<string, number>;
  groupCells?: Record<string, number>;
  refs?: Ref[];
  keyRefs?: Ref[];
  selection?: Selection | null;
  picked?: ReviewTarget | null;
  disabled?: boolean;
  handlers?: TableHandlers;
  marks?: Marks;
}) {
  const id = useId();
  const scroller = useRef<HTMLDivElement>(null);
  const resetKey = `${stage?.execution_version ?? ""}:${stage?.id ?? ""}:${role}:${inputRef ?? ""}`;
  const [expanded, setExpanded] = useState<string | null>(null);
  const open = expanded === resetKey;
  const visible = open ? data.rows.length : Math.min(PREVIEW_ROWS, data.rows.length);
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0;
  }, [resetKey]);

  const selectable = annotated && !!handlers.onCell;
  const drag = useTableDrag(
    scroller,
    data,
    stage,
    false,
    disabled,
    selectable ? handlers.onRange : undefined,
    { table_role: role, ...(inputRef ? { input_ref: inputRef } : {}) },
    pickedTarget,
  );

  const targetHere =
    !!pickedTarget &&
    (pickedTarget.table_role || "output") === role &&
    pickedTarget.input_ref === inputRef &&
    pickedTarget.step_id === stage?.id &&
    pickedTarget.operation_id === stage?.view_operation_id &&
    !pickedTarget.removed;
  const picked = useMemo(
    () => new Set(targetHere ? selectedCells(pickedTarget, data).map((c) => pointKey(c.row_id, c.column)) : []),
    [targetHere, pickedTarget, data],
  );
  const inputRows = useMemo(() => new Map(stage?.input?.rows.map((r) => [r.id, r]) || []), [stage?.input]);

  const overlaps = (sources: Ref[] | undefined, wanted: Ref[]) =>
    !!sources?.some((s) =>
      wanted.some(
        (w) => (w.table_id || "input") === (s.table_id || "input") && w.row_id === s.row_id && w.column === s.column,
      ),
    );
  const ownSources = (r: string, c: string) => (stage ? stage.lineage[r]?.[c] || [] : [{ row_id: r, column: c }]);

  const removedRows = annotated && inputDelta?.rowIdentity ? new Set(inputDelta.removedRows.map((r) => r.id)) : null;
  const columnPicked = (c: string) =>
    targetHere &&
    ((pickedTarget!.kind === "column" && pickedTarget!.column === c) ||
      (pickedTarget!.kind === "columns" && !!pickedTarget!.columns?.includes(c)));

  const pickEdges = (i: number, j: number, r: string, c: string) => {
    const has = (row?: string, col?: string) => !!row && !!col && picked.has(pointKey(row, col));
    const edges = [
      !has(data.rows[i - 1]?.id, c) && "inset 0 2px 0 var(--primary)",
      !has(data.rows[i + 1]?.id, c) && "inset 0 -2px 0 var(--primary)",
      !has(r, data.columns[j - 1]) && "inset 2px 0 0 var(--primary)",
      !has(r, data.columns[j + 1]) && "inset -2px 0 0 var(--primary)",
    ].filter(Boolean);
    return edges.join(", ") || undefined;
  };

  return (
    <div className="overflow-hidden rounded-md border bg-card">
      <div
        id={id}
        ref={scroller}
        role="region"
        aria-label="표"
        tabIndex={0}
        onPointerDown={selectable ? drag : undefined}
        onDragStart={selectable ? (e) => e.preventDefault() : undefined}
        className={cn("overflow-auto outline-none", open ? "max-h-[min(440px,58dvh)]" : "max-h-[300px]", selectable && "select-none")}
      >
        <table className="w-full border-collapse text-[13px] leading-5">
          <thead className="sticky top-0 z-10 bg-muted">
            <tr>
              <th className="w-10 border-b px-2 py-2 text-right text-xs font-normal text-muted-foreground">
                <span className="sr-only">행 번호</span>
              </th>
              {data.columns.map((c, j) => {
                const added = annotated && !!delta?.addedColumns.includes(c);
                const dropped = annotated && !!inputDelta?.removedColumns.includes(c);
                return (
                  <th
                    key={c}
                    scope="col"
                    data-drag-kind={selectable ? "column" : undefined}
                    data-ri={-1}
                    data-ci={j}
                    tabIndex={selectable && !disabled ? 0 : undefined}
                    onClick={
                      selectable
                        ? (e) => {
                            if (disabled || (e.target as HTMLElement).closest("button")) return;
                            handlers.onColumn?.(c, e.currentTarget, e.ctrlKey || e.metaKey);
                          }
                        : undefined
                    }
                    onKeyDown={
                      selectable
                        ? (e) => {
                            if (e.target === e.currentTarget && !disabled && (e.key === "Enter" || e.key === " ")) {
                              e.preventDefault();
                              handlers.onColumn?.(c, e.currentTarget, e.ctrlKey || e.metaKey);
                            }
                          }
                        : undefined
                    }
                    className={cn(
                      "border-b border-l px-3 py-2 text-left font-medium whitespace-nowrap",
                      selectable && "cursor-pointer hover:bg-secondary",
                      added && "bg-added text-added-foreground",
                      dropped && "bg-removed text-removed-foreground line-through decoration-1",
                      columnPicked(c) && "shadow-[inset_0_-2px_0_var(--primary)]",
                    )}
                  >
                    {added && stage ? <ColumnOrigin stage={stage} column={c} /> : c}
                    <MarkDot mark={marks?.get(`col:${c}`)} />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {data.rows.slice(0, visible).map((row, i) => {
              const gone = !!removedRows?.has(row.id);
              const moved = annotated && !!delta?.movedRows.has(row.id);
              return (
                <tr key={row.id} className={cn("border-b last:border-b-0", gone && "bg-removed/70 text-removed-foreground")}>
                  <td
                    data-drag-kind={selectable ? "row" : undefined}
                    data-ri={i}
                    data-ci={-1}
                    className={cn("px-1 text-right text-xs text-muted-foreground tabular-nums", moved && "bg-source text-source-foreground")}
                    title={gone ? "이 단계에서 제외된 행" : moved ? "순서가 바뀐 행" : undefined}
                  >
                    {selectable ? (
                      <button
                        type="button"
                        disabled={disabled}
                        aria-label={`${i + 1}행 선택`}
                        onClick={(e) => {
                          e.stopPropagation();
                          handlers.onRow?.(row.id, e.currentTarget, e.ctrlKey || e.metaKey);
                        }}
                        className="w-full rounded-sm px-1 py-1.5 text-right hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                      >
                        {i + 1}
                        <MarkDot mark={marks?.get(`row:${row.id}`)} />
                      </button>
                    ) : (
                      <span className="block px-1 py-1.5">{i + 1}</span>
                    )}
                  </td>
                  {data.columns.map((c, j) => {
                    const value = row.values[c];
                    const isPicked = targetHere && picked.has(pointKey(row.id, c));
                    const single =
                      selection &&
                      (selection.table_role || "output") === role &&
                      selection.input_ref === inputRef &&
                      selection.step === stage?.id &&
                      selection.row === row.id &&
                      selection.column === c;
                    const related = annotated && refs.length > 0 && overlaps(stage ? stage.lineage?.[row.id]?.[c] : ownSources(row.id, c), refs);
                    const keyRelated = annotated && keyRefs.length > 0 && overlaps(ownSources(row.id, c), keyRefs);
                    const changed = annotated && !!delta?.changedCells.has(cellKey(row.id, c));
                    const changedInput = annotated && !!inputDelta?.changedCells.has(cellKey(row.id, c));
                    const added = annotated && !!delta?.addedColumns.includes(c);
                    const group = annotated ? (groupCells?.[cellKey(row.id, c)] ?? groupRows?.[row.id]) : undefined;
                    const title = changed
                      ? `이전 값: ${fmt(inputRows.get(row.id)?.values[c]) || "빈칸"}`
                      : group !== undefined
                        ? `그룹 ${group + 1}`
                        : undefined;
                    const style: CSSProperties = {};
                    if (group !== undefined) {
                      style.backgroundColor = groupColor(group);
                      style.boxShadow = j === 0 ? `inset 3px 0 0 ${groupBorder(group)}` : undefined;
                    }
                    if (isPicked) style.boxShadow = pickEdges(i, j, row.id, c);
                    return (
                      <td
                        key={c}
                        data-drag-kind={selectable ? "cell" : undefined}
                        data-ri={i}
                        data-ci={j}
                        tabIndex={selectable && !disabled ? 0 : undefined}
                        title={title}
                        style={style}
                        data-mark={marks?.get(`cell:${pointKey(row.id, c)}`)}
                        onClick={
                          selectable
                            ? (e) => {
                                if (!disabled) handlers.onCell?.(row.id, c, e.currentTarget, e.ctrlKey || e.metaKey);
                              }
                            : undefined
                        }
                        onKeyDown={
                          selectable
                            ? (e) => {
                                if (!disabled && (e.key === "Enter" || e.key === " ")) {
                                  e.preventDefault();
                                  handlers.onCell?.(row.id, c, e.currentTarget, e.ctrlKey || e.metaKey);
                                }
                              }
                            : undefined
                        }
                        className={cn(
                          "relative max-w-[28ch] truncate border-l px-3 py-1.5 align-top",
                          typeof value === "number" && "text-right tabular-nums",
                          selectable && "cursor-cell focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                          added && group === undefined && "bg-added/60",
                          (changed || changedInput) && "bg-changed text-changed-foreground",
                          related && "bg-source text-source-foreground",
                          keyRelated && "underline decoration-source-foreground decoration-2 underline-offset-2",
                          gone && "line-through decoration-1",
                          isPicked && "bg-accent",
                          single && "bg-accent",
                        )}
                      >
                        {value == null || value === "" ? (
                          <span className="text-muted-foreground/60">빈칸</span>
                        ) : (
                          fmt(value)
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {!data.rows.length && <p className="px-3 py-6 text-center text-sm text-muted-foreground">행이 없습니다</p>}
      </div>
      {data.rows.length > PREVIEW_ROWS && (
        <div className="flex items-center justify-between border-t bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground">
          <span className="tabular-nums">
            {open ? `${data.rows.length}행 전체` : `${data.rows.length}행 중 ${visible}행`}
          </span>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={id}
            onClick={() => setExpanded(open ? null : resetKey)}
            className="rounded-sm px-2 py-1 font-medium text-foreground hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {open ? "접기" : "모두 보기"}
          </button>
        </div>
      )}
    </div>
  );
}

/** Review-history channel: a small neutral mark, separate from the change colors. */
function MarkDot({ mark }: { mark?: "viewed" | "checked" }) {
  if (!mark) return null;
  return (
    <span
      className={cn("ml-1.5 inline-block size-1.5 rounded-full align-middle", mark === "checked" ? "bg-foreground" : "ring-1 ring-foreground/50")}
      title={mark === "checked" ? "확인 표시함" : "근거를 열어 봄"}
    >
      <span className="sr-only">{mark === "checked" ? "확인 표시함" : "근거를 열어 봄"}</span>
    </span>
  );
}
