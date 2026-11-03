"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, RefreshCw } from "lucide-react";
import { fmt, type Stage, type SourceContext } from "@/lib/trace";
import { PythonCode } from "./python-code";
import { useAnchoredPosition, useDismiss } from "./anchored-comment";
import { transformations, type ChangeTarget, type Transformation } from "./workspace-diff";

export const CHANGE_LABEL = { added: "추가", changed: "변경", removed: "삭제" };

export function TransformationBubble({ anchor, stage, target, onClose, onRefresh, refreshing, onSelect }: { anchor: HTMLElement; stage: Stage; target: ChangeTarget; onClose: () => void; onRefresh?: () => void; refreshing?: boolean; onSelect?: (item: Transformation) => void }) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const pos = useAnchoredPosition(anchor, panel, true);
  useDismiss(anchor, panel, onClose, false);
  useLayoutEffect(() => { close.current?.focus({ preventScroll: true }); }, [anchor]);
  const title = target.column ? `“${target.column}”${target.row ? ` · ${target.row.number}행` : " 열"}` : `${target.row?.number}행`;
  const value = (v: unknown) => v === undefined ? "없음" : v === null ? "null" : fmt(v as Parameters<typeof fmt>[0]);
  const items = transformations(stage, target);
  const [selectedId, setSelectedId] = useState("");
  const selected = items.find((item, i) => (item.id || String(i)) === selectedId) || items[0];
  useEffect(() => { if (selected?.id) onSelect?.(selected); }, [selected?.id, selected?.code, onSelect]);
  return createPortal(<div ref={panel} role="dialog" aria-modal="false" aria-labelledby="transformation-title"
    className="transformation-bubble" data-side={pos.above ? "top" : "bottom"}
    style={{ left: pos.left, top: pos.top, visibility: pos.visible ? "visible" : "hidden", "--arrow-left": `${pos.arrowLeft}px` } as React.CSSProperties}
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); anchor.focus({ preventScroll: true }); onClose(); } }}>
    <div className="transformation-arrow" aria-hidden="true" />
    <header className="transformation-heading"><span className={`change-badge change-${target.kind}`}>{CHANGE_LABEL[target.kind]}</span>
      <h2 id="transformation-title">{title}</h2>
      {onRefresh && <button type="button" className="bubble-refresh" aria-label="개별 변환 설명 갱신" title="현재 실행의 개별 변환 설명 갱신" disabled={refreshing} onClick={onRefresh}><RefreshCw size={12} className={refreshing ? "animate-spin" : ""} />{refreshing ? "갱신 중" : "설명 갱신"}</button>}
      <button ref={close} type="button" className="bubble-close" aria-label="변환 설명 닫기" onClick={() => { anchor.focus({ preventScroll: true }); onClose(); }}><X size={15} /></button>
    </header>
    {target.cell && <div className="transformation-values"><span>변환 전 <strong>{value(target.cell.before)}</strong></span><span aria-hidden="true">→</span><span>변환 후 <strong>{value(target.cell.after)}</strong></span></div>}
    {items.length > 1 && <label className="transformation-picker">{items.some(item => item.candidates) ? "이 영역의 변환을 선택하세요" : "관련 변환"}
      <select aria-label="설명할 변환 선택" value={selected?.id || String(items.indexOf(selected!))} onChange={event => setSelectedId(event.target.value)}>
        {items.map((item, i) => <option value={item.id || String(i)} key={item.id || i}>{i+1}. {item.line ? `L${item.line.start} · ` : ""}{item.text.slice(0,70)}</option>)}
      </select></label>}
    <div className="transformation-content">{selected ? <section className="transformation-operation">
      <p>{selected.text}</p>
      {selected.context && !selected.context.complete && selected.context.unresolved.length > 0 && <div className="source-context-note">정의 경로의 일부만 확인했습니다: {selected.context.unresolved.join(", ")}</div>}
      <div className="transformation-code"><div className="transformation-code-label">현재 연산 · 수정 대상{selected.line && <span>L{selected.line.start}{selected.line.start_column !== undefined ? `:${(selected.line.start_character ?? selected.line.start_column)+1}` : ""}{selected.line.end !== selected.line.start ? `–L${selected.line.end}` : ""}</span>}</div><PythonCode code={selected.code} focus={selected.focus} startLine={selected.line?.start ?? 1} /></div>
      <ReferenceDefinitions context={selected.context} />
      {selected.source === "ast" && <span className="transformation-source">코드 분석으로 작성한 설명</span>}
    </section> : <p className="transformation-operation">이 영역에 대응하는 개별 변환 코드가 확인되지 않았습니다.</p>}</div>
  </div>, document.body);
}

export function ReferenceDefinitions({ context }: { context?: SourceContext }) {
  if (!context?.definitions.length) return null;
  return <details className="source-definitions" open><summary>원본 열까지의 변수 정의 <span>참고용</span></summary>
    {context.definitions.map((definition,i) => <div className="transformation-code source-definition" key={`${definition.symbol}:${definition.code_location.start}:${i}`}>
      <div className="transformation-code-label">{definition.symbol}<span>L{definition.code_location.start}{definition.code_location.end !== definition.code_location.start ? `–${definition.code_location.end}` : ""}</span></div>
      <PythonCode code={definition.code} startLine={definition.code_location.start} />
    </div>)}
  </details>;
}
