"use client";

import { useEffect, useRef } from "react";
import { fmt, type Table } from "@/lib/trace";

/** A complete executed table with independent scrolling and a fixed header. */
export function WorkspaceTable({ data, identity }: { data: Table; identity: string }) {
  const viewport = useRef<HTMLDivElement>(null);
  useEffect(() => { viewport.current?.scrollTo({ top: 0, left: 0 }); }, [identity]);
  return <div className="workspace-table-scroll" ref={viewport} tabIndex={0} role="region" aria-label="테이블 스크롤">
    <table className="workspace-table">
      <thead><tr><th className="row-index" scope="col">#</th>{data.columns.map((column) => <th scope="col" key={column} title={column}>{column}</th>)}</tr></thead>
      <tbody>{data.rows.map((row, index) => <tr key={row.id}><th className="row-index" scope="row">{index + 1}</th>{data.columns.map((column) => <td key={column} className={typeof row.values[column] === "number" ? "is-number" : undefined}>
        {row.values[column] == null ? <span className="null-value">null</span> : typeof row.values[column] === "boolean" ? String(row.values[column]) : fmt(row.values[column])}
      </td>)}</tr>)}</tbody>
    </table>
    {!data.rows.length && <div className="empty-table-label">0행</div>}
  </div>;
}
