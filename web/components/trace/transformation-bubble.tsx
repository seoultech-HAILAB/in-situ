"use client";

import { useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { fmt, type Stage } from "@/lib/trace";
import { PythonCode } from "./python-code";
import { useAnchoredPosition, useDismiss } from "./anchored-comment";
import { transformations, type ChangeTarget } from "./workspace-diff";

export const CHANGE_LABEL = { added: "추가", changed: "변경", removed: "삭제" };

export function TransformationBubble({ anchor, stage, target, onClose }: { anchor: HTMLElement; stage: Stage; target: ChangeTarget; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const pos = useAnchoredPosition(anchor, panel, true);
  useDismiss(anchor, panel, onClose, false);
  useLayoutEffect(() => { close.current?.focus({ preventScroll: true }); }, [anchor]);
  const title = target.column ? `“${target.column}”${target.row ? ` · ${target.row.number}행` : " 열"}` : `${target.row?.number}행`;
  const value = (v: unknown) => v === undefined ? "없음" : v === null ? "null" : fmt(v as Parameters<typeof fmt>[0]);
  return createPortal(<div ref={panel} role="dialog" aria-modal="false" aria-labelledby="transformation-title"
    className="transformation-bubble" data-side={pos.above ? "top" : "bottom"}
    style={{ left: pos.left, top: pos.top, visibility: pos.visible ? "visible" : "hidden", "--arrow-left": `${pos.arrowLeft}px` } as React.CSSProperties}
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); anchor.focus({ preventScroll: true }); onClose(); } }}>
    <div className="transformation-arrow" aria-hidden="true" />
    <header className="transformation-heading"><span className={`change-badge change-${target.kind}`}>{CHANGE_LABEL[target.kind]}</span>
      <h2 id="transformation-title">{title}</h2>
      <button ref={close} type="button" className="bubble-close" aria-label="변환 설명 닫기" onClick={() => { anchor.focus({ preventScroll: true }); onClose(); }}><X size={15} /></button>
    </header>
    {target.cell && <div className="transformation-values"><span>변환 전 <strong>{value(target.cell.before)}</strong></span><span aria-hidden="true">→</span><span>변환 후 <strong>{value(target.cell.after)}</strong></span></div>}
    <div className="transformation-content">{transformations(stage, target).map((item, i) => <section className="transformation-operation" key={i}>
      <p>{item.text}</p><div className="transformation-code"><div className="transformation-code-label">Python{item.line && <span>L{item.line.start}{item.line.end !== item.line.start ? `–${item.line.end}` : ""}</span>}</div><PythonCode code={item.code} /></div>
    </section>)}</div>
  </div>, document.body);
}
