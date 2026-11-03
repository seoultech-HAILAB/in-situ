"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fmt, type Stage, type Table } from "@/lib/trace";
import { workspaceDiff, type ChangeTarget } from "./workspace-diff";
import { CHANGE_LABEL, TransformationBubble } from "./transformation-bubble";

const cellValue = (value: Parameters<typeof fmt>[0]) => value === undefined ? <span className="absent-value">—</span> : value === null ? <span className="null-value">null</span> : typeof value === "boolean" ? String(value) : fmt(value);

/** Deleted values are visible annotations; the executed result stays unchanged. */
export function WorkspaceTable({ data, identity, stage }: { data: Table; identity: string; stage?: Stage }) {
  const viewport = useRef<HTMLDivElement>(null);
  const [picked, setPicked] = useState<{ anchor: HTMLElement; target: ChangeTarget; key: string } | null>(null);
  const diff = useMemo(() => stage ? workspaceDiff(stage) : null, [stage]);
  const dismiss = useCallback(() => setPicked(null), []);
  useEffect(() => { viewport.current?.scrollTo({ top: 0, left: 0 }); setPicked(null); }, [identity]);
  function trigger(target: ChangeTarget, key: string, label: string, children: ReactNode) {
    return <button type="button" className="change-trigger" aria-label={`${label} · ${CHANGE_LABEL[target.kind]} · 변환 설명 보기`}
      aria-haspopup="dialog" aria-expanded={picked?.key === key} data-active={picked?.key === key}
      onClick={event => { const anchor = event.currentTarget; setPicked(current => current?.key === key ? null : { anchor, target, key }); }}>{children}</button>;
  }
  return <>
    {diff && <div className="table-change-legend" aria-label="테이블 변경 표시">
      <span><i className="change-added" />추가</span><span><i className="change-changed" />변경</span><span><i className="change-removed" />삭제</span>
      <span className="legend-hint">색이 있는 영역을 눌러 변환 보기</span>
    </div>}
    <div className="workspace-table-scroll" ref={viewport} tabIndex={0} role="region" aria-label="테이블 스크롤">
      <table className={`workspace-table ${diff ? "in-situ-table" : ""}`}>
        <thead><tr><th className="row-index" scope="col">#</th>{diff ? diff.columns.map(column => <th scope="col" key={column.name} data-change={column.kind}>
          {column.kind ? trigger({ kind: column.kind, column: column.name }, `column:${column.name}`, `${column.name} 열`, <>{column.name}<span className="column-change-mark" aria-hidden="true">{column.kind === "added" ? "+" : column.kind === "removed" ? "−" : "~"}</span></>) : column.name}
        </th>) : data.columns.map(column => <th scope="col" key={column} title={column}>{column}</th>)}</tr></thead>
        <tbody>{diff ? diff.rows.map(row => <tr key={row.key} data-row-change={row.kind}>
          <th scope="row" className="row-index" data-change={row.kind}>{row.kind ? trigger({ kind: row.kind, row }, row.key, `${row.number}행`, <>{row.kind === "removed" ? "−" : row.kind === "added" ? "+" : ""}{row.number}</>) : row.number}</th>
          {diff.columns.map(column => { const cell = row.cells[column.name]; return <td key={column.name} data-change={cell.kind} className={typeof cell.value === "number" ? "is-number" : undefined}>
            {cell.kind ? trigger({ kind: cell.kind, row, column: column.name, cell }, `${row.key}:${column.name}`, `${row.number}행 ${column.name}`, cellValue(cell.value)) : cellValue(cell.value)}
          </td>; })}
        </tr>) : data.rows.map((row, index) => <tr key={row.id}><th className="row-index" scope="row">{index + 1}</th>{data.columns.map(column => <td key={column} className={typeof row.values[column] === "number" ? "is-number" : undefined}>{cellValue(row.values[column])}</td>)}</tr>)}</tbody>
      </table>
      {!(diff ? diff.rows.length : data.rows.length) && <div className="empty-table-label">0행</div>}
    </div>
    {diff && (diff.removedRows > 0 || diff.removedColumns > 0) && <div className="removed-data-note">삭제된 {diff.removedRows > 0 ? `${diff.removedRows}행` : ""}{diff.removedRows > 0 && diff.removedColumns > 0 ? " · " : ""}{diff.removedColumns > 0 ? `${diff.removedColumns}열` : ""}은 빨간색으로 남겨 표시합니다. 결과 CSV에는 포함되지 않습니다.</div>}
    {picked && stage && <TransformationBubble anchor={picked.anchor} target={picked.target} stage={stage} onClose={dismiss} />}
  </>;
}
