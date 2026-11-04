"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Stage } from "@/lib/trace";

const operations: Record<string, string> = {
  sum: "합계",
  mean: "평균",
  min: "최솟값",
  max: "최댓값",
  count: "빈칸을 뺀 개수",
  size: "행 개수",
  nunique: "고유값 개수",
  median: "중앙값",
  first: "첫 값",
  last: "마지막 값",
  prod: "곱",
};

/** How a column was produced, using only verified trace metadata. */
export function columnOrigin(stage: Stage, column: string) {
  const direct =
    stage.trace_level === "detailed" && (stage.params.formulas?.[column] || stage.params.aggregations?.[column]);
  const operation = direct
    ? stage
    : [...(stage.operations || [])]
        .reverse()
        .find((op) => op.trace_level === "detailed" && (op.params.formulas?.[column] || op.params.aggregations?.[column]));
  const formula = operation?.params.formulas?.[column];
  const aggregation = operation?.params.aggregations?.[column];
  const sources = formula?.sources || (aggregation ? [aggregation.column === "*" ? "그룹의 행" : aggregation.column] : []);
  const explained = stage.column_explanations?.[column] || operation?.column_explanations?.[column];
  const keys = operation?.params.keys?.length ? `${operation.params.keys.join(", ")}별 ` : "";
  const fallback =
    aggregation && operations[aggregation.operation]
      ? `${keys}${aggregation.column === "*" ? "" : aggregation.column + "의 "}${operations[aggregation.operation]}`
      : null;
  return { sources, text: explained || fallback };
}

export function ColumnOriginDetails({ stage, column }: { stage: Stage; column: string }) {
  const { sources, text } = columnOrigin(stage, column);
  return (
    <div className="space-y-1.5 text-sm">
      {sources.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {sources.join(", ")} 열에서 만든 열
        </p>
      )}
      <p>{text || "만든 방법을 확인하지 못했습니다."}</p>
    </div>
  );
}

export function ColumnOrigin({ stage, column }: { stage: Stage; column: string }) {
  return (
    <Popover>
      <PopoverTrigger
        className="-mx-1 inline-flex items-center gap-1 rounded-sm px-1 font-medium underline decoration-dotted underline-offset-4 hover:bg-added focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <span aria-hidden>+</span>
        {column}
        <span className="sr-only">, 새로 생긴 열. 만든 방법 보기</span>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72">
        <p className="font-medium">{column}</p>
        <ColumnOriginDetails stage={stage} column={column} />
      </PopoverContent>
    </Popover>
  );
}
