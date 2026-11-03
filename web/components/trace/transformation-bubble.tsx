"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, RefreshCw } from "lucide-react";
import { fmt, type Stage } from "@/lib/trace";
import { TransformationDetails } from "./transformation-details";
import { useAnchoredPosition, useDismiss } from "./anchored-comment";
import { transformations, type ChangeTarget } from "./workspace-diff";

export const CHANGE_LABEL = { added: "추가", changed: "변경", removed: "삭제" };

export function TransformationBubble({ anchor, stage, target, onClose, onRefresh, refreshing }: { anchor: HTMLElement; stage: Stage; target: ChangeTarget; onClose: () => void; onRefresh?: () => void; refreshing?: boolean }) {
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
    <div className="transformation-content">{selected ? <TransformationDetails item={selected} /> : <p className="transformation-operation">이 영역에 대응하는 개별 변환 코드가 확인되지 않았습니다.</p>}</div>
  </div>, document.body);
}
