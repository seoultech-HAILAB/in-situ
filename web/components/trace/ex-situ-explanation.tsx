import type { Stage } from "@/lib/trace";
import { availableTransformations, transformationDetails } from "./workspace-diff";
import { TransformationDetails } from "./transformation-details";
import { DirectUsedTables } from "./direct-used-tables";

type ExplanationItem = NonNullable<Stage["transformations"]>[number];
type ChangeKind = "added" | "changed" | "removed";
const CHANGE_NAMES = { added: "추가", changed: "변환", removed: "제거" };

function changeHeadings(item: ExplanationItem): { names: string[]; kind?: ChangeKind }[] {
  const bindings = item.revision_effects ?? item.execution_effects ?? [];
  const columns = { added: new Set<string>(), changed: new Set<string>(), removed: new Set<string>() };
  for (const effect of bindings) {
    for (const kind of ["added", "changed", "removed"] as const) {
      for (const column of effect.columns[kind]) columns[kind].add(column);
    }
  }
  // Clearing cells or removing rows does not remove the column itself.
  // Treat changes within surviving columns as transformations, and describe
  // row-only operations separately rather than coloring every field red.
  for (const effect of bindings) {
    const rowEvents = new Set([...effect.rows.added, ...effect.rows.removed]);
    for (const cells of Object.values(effect.cells)) {
      for (const [column,rows] of Object.entries(cells)) {
        if (rows.some(row => !rowEvents.has(row)) && !columns.added.has(column) && !columns.removed.has(column)) columns.changed.add(column);
      }
    }
  }
  const headings = (["added", "changed", "removed"] as const)
    .filter(kind => columns[kind].size)
    .map(kind => ({ kind, names: [...columns[kind]] }));
  if (headings.length) return headings;
  const rowHeadings = (["added", "removed", "changed"] as const)
    .filter(kind => bindings.some(effect => effect.rows[kind].length))
    .map(kind => ({ kind, names: [kind === "changed" && bindings.some(effect => effect.rows.reordered.length) ? "행 순서" : "행"] }));
  if (rowHeadings.length) return rowHeadings;
  return [{ names: item.output_columns.length ? item.output_columns : ["열 대응 미확인"] }];
}

export function ExSituExplanation({ step, number, label }: {
  step?: Stage; number: number; label?: string;
}) {
  const items = step ? availableTransformations(step) : [];
  return <section className="explanation-pane" aria-label="코드 자연어 설명">
    <div className="pane-toolbar"><span>코드 설명</span>
      {step && <span className="explanation-step-label">{label ?? `Step ${String(number).padStart(2,"0")}`}</span>}
    </div>
    <div className="explanation-scroll" key={`${step?.execution_version}:${step?.id}`}>
      {!step ? <div className="explanation-empty">과제를 실행하면 선택한 Step의 코드 설명이 여기에 표시됩니다.</div> : <>
        <DirectUsedTables tables={step.direct_tables ?? []} identity={`${step.execution_version}:${step.id}`} />
        {items.length > 0 ? <ol className="explanation-operations">{items.map(item => <li key={item.id}>
          <h3 className="explanation-change-heading">{changeHeadings(item).map((heading,index) => <span key={index}
            className={`explanation-change-group${heading.kind ? ` change-${heading.kind}` : ""}`} data-change-kind={heading.kind}>
            <span className="explanation-change-columns">{heading.names.join(", ")}</span>
            {heading.kind && <span className="explanation-change-type">{CHANGE_NAMES[heading.kind]}</span>}
          </span>)}</h3>
          <TransformationDetails item={transformationDetails(item)} plainCode />
        </li>)}</ol> : <p className="explanation-empty">{step.nl_explanation?.text ?? "설명이 없습니다."}</p>}
      </>}
    </div>
  </section>;
}
