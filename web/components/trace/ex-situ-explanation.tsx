import { RefreshCw } from "lucide-react";
import type { Stage, RevisionPreview } from "@/lib/trace";
import { availableTransformations, transformationDetails } from "./workspace-diff";
import { TransformationDetails } from "./transformation-details";

export function ExSituExplanation({ step, number, label, revision, busy, error, onRefresh }: {
  step?: Stage; number: number; label?: string; revision?: RevisionPreview | null; busy?: boolean; error?: string; onRefresh?: () => void;
}) {
  const items = step ? availableTransformations(step) : [];
  return <section className="explanation-pane" aria-label="코드 자연어 설명">
    <div className="pane-toolbar"><span>코드 설명</span>
      {step && <span className="explanation-step-label">{label ?? `Step ${String(number).padStart(2,"0")}`}</span>}
      {onRefresh && <button type="button" className="explanation-refresh" aria-label="코드 자연어 설명 갱신" disabled={busy} onClick={onRefresh}>
        <RefreshCw size={12} className={busy ? "animate-spin" : ""} />{busy ? "갱신 중" : "설명 갱신"}
      </button>}
    </div>
    <div className="explanation-scroll" key={`${step?.execution_version}:${step?.id}`}>
      {!step ? <div className="explanation-empty">과제를 실행하면 선택한 Step의 코드 설명이 여기에 표시됩니다.</div> : <>
        {revision && <div className="explanation-revision"><strong>{revision.label} · 수정 내용</strong><p>{revision.request}</p>{revision.assumptions?.map((text,index) => <p key={index}>{text}</p>)}</div>}
        {error && <p className="explanation-notice" role="status">자연어 설명을 불러오지 못했습니다. 확인 가능한 코드 분석 설명을 표시합니다. {error}</p>}
        {step.nl_explanation && <div className="explanation-summary"><h2>{step.nl_explanation.title}</h2><p>{step.nl_explanation.text}</p></div>}
        {items.length > 0 ? <ol className="explanation-operations">{items.map(item => <li key={item.id}>
          <div className="explanation-operation-meta"><span className="explanation-line">L{item.code_location.start}{item.code_location.end !== item.code_location.start ? `–${item.code_location.end}` : ""}</span>
            {item.output_columns.length > 0 && <span>{item.output_columns.join(", ")}</span>}
            {item.description.source === "ast" && <span className="explanation-source">코드 분석</span>}
          </div><TransformationDetails item={transformationDetails(item)} />
        </li>)}</ol> : !step.nl_explanation && <p className="explanation-empty">현재 Step에 대한 설명이 아직 없습니다.</p>}
      </>}
    </div>
  </section>;
}
