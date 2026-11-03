import { fmt, type ReviewTarget, type Table } from "@/lib/trace";

const rowNumber = (data: Table, id?: string) => data.rows.findIndex((r) => r.id === id) + 1;
const show = (v: Parameters<typeof fmt>[0]) => fmt(v) || "빈칸";

/** Plain-language label and a short value preview for the comment panel. */
export function describeTarget(target: ReviewTarget, data: Table): { title: string; preview: string } {
  const where = target.table_role === "input" ? "변환 전 표" : "변환 후 표";
  switch (target.kind) {
    case "step":
      return { title: "이 단계 전체", preview: "" };
    case "cell": {
      const row = data.rows.find((r) => r.id === target.row_id);
      return { title: `${where}, ${rowNumber(data, target.row_id)}행 ${target.column}`, preview: show(row?.values[target.column!]) };
    }
    case "row": {
      const row = data.rows.find((r) => r.id === target.row_id);
      return {
        title: `${where}, ${rowNumber(data, target.row_id)}행`,
        preview: data.columns.slice(0, 6).map((c) => `${c}: ${show(row?.values[c])}`).join("\n"),
      };
    }
    case "column":
      return {
        title: `${where}, ${target.column} 열`,
        preview: data.rows.slice(0, 5).map((r) => show(r.values[target.column!])).join(", ") + (data.rows.length > 5 ? " 외" : ""),
      };
    case "cells":
      if (target.cells)
        return {
          title: `${where}, 셀 ${target.cells.length}개`,
          preview: target.cells
            .slice(0, 4)
            .map((p) => `${rowNumber(data, p.row_id)}행 ${p.column}: ${show(data.rows.find((r) => r.id === p.row_id)?.values[p.column])}`)
            .join("\n"),
        };
    // falls through: rectangular drag selection
    default: {
      const rows = target.row_ids ? data.rows.filter((r) => target.row_ids!.includes(r.id)) : data.rows;
      const columns = target.columns || data.columns;
      return {
        title: `${where}, ${rows.length}행 ${columns.length}열`,
        preview: `${columns.slice(0, 5).join(", ")}${columns.length > 5 ? " 외" : ""}`,
      };
    }
  }
}
