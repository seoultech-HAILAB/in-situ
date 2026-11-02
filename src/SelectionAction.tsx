import { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Pencil,X,GitBranch } from 'lucide-react';
import type { ReactNode } from 'react';

export function SelectionAction({ anchor, onEdit, onDismiss, lineage, columnInfo }: {
  anchor: HTMLElement; onEdit: (button: HTMLElement) => void; onDismiss: () => void;
  lineage?:{count:number;known:boolean;content:ReactNode};
  columnInfo?:ReactNode;
}) {
  const action=useRef<HTMLDivElement>(null);
  const sources=useRef<HTMLDialogElement>(null);
  const [position,setPosition]=useState({left:12,top:12,visibility:'hidden' as 'hidden'|'visible'});
  useLayoutEffect(()=>{
    let frame=0;
    const place=()=>{
      if (!anchor.isConnected || !action.current) {setPosition(p=>({...p,visibility:'hidden'}));return;}
      const a=anchor.getBoundingClientRect(),b=action.current.getBoundingClientRect();
      const clip=anchor.closest('.table-viewport')?.getBoundingClientRect();
      const inTable=!clip||(a.bottom>clip.top&&a.top<clip.bottom&&a.right>clip.left&&a.left<clip.right);
      setPosition({left:Math.max(8,Math.min(a.right-8,innerWidth-b.width-8)),
        top:Math.max(8,Math.min(a.bottom+5,innerHeight-b.height-8)),
        visibility:inTable&&a.bottom>0&&a.top<innerHeight&&a.right>0&&a.left<innerWidth?'visible':'hidden'});
    };
    const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(place);};
    const observer=new ResizeObserver(schedule);if(action.current)observer.observe(action.current);
    place();window.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);
    return()=>{cancelAnimationFrame(frame);observer.disconnect();window.removeEventListener('scroll',schedule,true);window.removeEventListener('resize',schedule);};
  },[anchor]);
  useLayoutEffect(()=>{
    const outside=(e:PointerEvent)=>{if(e.target instanceof Node&&!action.current?.contains(e.target)&&!anchor.contains(e.target))onDismiss();};
    const escape=(e:KeyboardEvent)=>{if(e.key==='Escape')onDismiss();};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};
  },[anchor,onDismiss]);
  return createPortal(<div className={'selection-action'+(columnInfo?' with-column-info':'')} ref={action} style={position} role="toolbar" aria-label="선택 영역 작업">
    <button onClick={e=>onEdit(e.currentTarget)}><Pencil size={13}/>수정</button>
    {lineage&&<><button onClick={()=>sources.current?.showModal()}><GitBranch size={13}/>{lineage.count?`출처 ${lineage.count}`:lineage.known?'출처 보기':'출처 미확인'}</button><dialog className="lineage-preview" ref={sources} onClick={e=>{if(e.target===e.currentTarget)sources.current?.close();}}><div className="drawer-header"><h3>확인된 원본 출처</h3><button aria-label="출처 닫기" onClick={()=>sources.current?.close()}><X size={17}/></button></div>{lineage.content}</dialog></>}
    {columnInfo&&<div className="selection-column-info">{columnInfo}</div>}
  </div>,document.body);
}
