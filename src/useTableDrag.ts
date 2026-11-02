import { useEffect, useRef } from 'react';
import type { PointerEvent as ReactPointerEvent, RefObject } from 'react';
import type { ReviewTarget, Stage, Table } from './types';
import {combineSelection} from './tableSelection';

type Pick = (target: ReviewTarget, anchor: HTMLElement, final: boolean) => void;

export function useTableDrag(root: RefObject<HTMLDivElement | null>, data: Table, stage: Stage | undefined,
  removed: boolean, disabled: boolean, onPick?: Pick, identity:{table_role?:'input'|'output';input_ref?:string}={},previous?:ReviewTarget|null) {
  const cleanup = useRef<() => void>(() => {});
  useEffect(() => () => cleanup.current(), []);
  return (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!onPick || !stage || disabled || event.button !== 0 || event.pointerType === 'touch') return;
    const start = (event.target as HTMLElement).closest<HTMLElement>('[data-drag-kind]');
    const container = root.current;
    if (!start || !container?.contains(start)) return;
    cleanup.current();
    const kind = start.dataset.dragKind!, r0 = Number(start.dataset.ri), c0 = Number(start.dataset.ci);
    let lastRow = r0, lastColumn = c0, dragged = false, frame = 0;
    let x = event.clientX, y = event.clientY, anchor = start;
    const rectangle = (): ReviewTarget => ({
      kind: kind === 'row' ? 'rows' : kind === 'column' ? 'columns' : 'cells',
      step_id: stage.id, operation_id: stage.view_operation_id, removed,
      ...identity,
      ...(kind !== 'column' ? { row_ids: data.rows.slice(Math.min(r0,lastRow),Math.max(r0,lastRow)+1).map(r=>r.id) } : {}),
      ...(kind !== 'row' ? { columns: data.columns.slice(Math.min(c0,lastColumn),Math.max(c0,lastColumn)+1) } : {}),
    });
    const target=()=>event.ctrlKey||event.metaKey?combineSelection(previous,rectangle(),data,false)!:rectangle();
    const point = () => {
      const box = container.getBoundingClientRect();
      const px = Math.max(box.left+2,Math.min(x,box.right-2));
      const py = Math.max(box.top+2,Math.min(y,box.bottom-2));
      const hit = document.elementFromPoint(px,py)?.closest<HTMLElement>('[data-drag-kind]');
      if (!hit || !container.contains(hit) || hit.dataset.dragKind !== kind) return;
      const row = Number(hit.dataset.ri), column = Number(hit.dataset.ci);
      if (row === lastRow && column === lastColumn) return;
      lastRow = row; lastColumn = column; anchor = hit;
      dragged = true; onPick(target(),anchor,false);
    };
    const move = (e: PointerEvent) => {
      if (e.pointerId !== event.pointerId) return;
      x=e.clientX; y=e.clientY;
      if (Math.hypot(x-event.clientX,y-event.clientY)>4) point();
      if (dragged) e.preventDefault();
    };
    const scroll = () => {
      if (dragged) {
        const b=container.getBoundingClientRect();
        if (kind !== 'row' && container.scrollWidth>container.clientWidth)
          container.scrollLeft += x>b.right-24 ? 14 : x<b.left+24 ? -14 : 0;
        if (kind !== 'column' && container.scrollHeight>container.clientHeight)
          container.scrollTop += y>b.bottom-24 ? 14 : y<b.top+24 ? -14 : 0;
        point();
      }
      frame=requestAnimationFrame(scroll);
    };
    const stop = () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove',move);
      window.removeEventListener('pointerup',up);
      window.removeEventListener('pointercancel',cancel);
      window.removeEventListener('blur',cancel);
    };
    const up = (e: PointerEvent) => {
      if (e.pointerId !== event.pointerId) return;
      stop();
      if (dragged) {
        onPick(target(),anchor,true);
        const suppress = (click: MouseEvent) => { click.preventDefault(); click.stopImmediatePropagation(); };
        window.addEventListener('click',suppress,true);
        setTimeout(()=>window.removeEventListener('click',suppress,true),0);
      }
    };
    const cancel = () => { stop(); if (dragged) onPick(target(),anchor,true); };
    window.addEventListener('pointermove',move,{passive:false});
    window.addEventListener('pointerup',up);
    window.addEventListener('pointercancel',cancel);
    window.addEventListener('blur',cancel);
    frame=requestAnimationFrame(scroll);
    cleanup.current=stop;
  };
}
