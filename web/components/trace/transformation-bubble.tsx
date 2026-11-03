"use client";

import { useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { Stage } from "@/lib/trace";
import { TransformationDetails } from "./transformation-details";
import { useAnchoredPosition, useDismiss } from "./anchored-comment";
import { transformations, type ChangeTarget } from "./workspace-diff";

export const CHANGE_LABEL = { added: "추가", changed: "변경", removed: "삭제" };

export function TransformationBubble({ anchor, stage, target, onClose }: { anchor: HTMLElement; stage: Stage; target: ChangeTarget; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  const pos = useAnchoredPosition(anchor, panel, true);
  useDismiss(anchor, panel, onClose, false);
  useLayoutEffect(() => { panel.current?.focus({ preventScroll: true }); }, [anchor]);
  const items = transformations(stage, target);
  return createPortal(<div ref={panel} role="dialog" aria-modal="false" aria-label="변환 설명" tabIndex={-1}
    className="transformation-bubble" data-side={pos.above ? "top" : "bottom"}
    style={{ left: pos.left, top: pos.top, visibility: pos.visible ? "visible" : "hidden", "--arrow-left": `${pos.arrowLeft}px` } as React.CSSProperties}
    onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); anchor.focus({ preventScroll: true }); onClose(); } }}>
    <div className="transformation-arrow" aria-hidden="true" />
    <div className="transformation-content">{items.length ? items.map((item,index) => <TransformationDetails key={item.id ?? index} item={item} />) : <p>연결된 코드를 확인하지 못했습니다.</p>}</div>
  </div>, document.body);
}
