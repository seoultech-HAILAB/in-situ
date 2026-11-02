import {useEffect,useId,useRef,useState,type HTMLAttributes,type ReactNode,type RefObject} from 'react';

/** A shared head preview. Expanding reveals all rows inside a bounded scroller. */
export function TableViewport({rowCount,identity,resetKey='',previewRows=5,scrollRef,scrollProps,className='',children}:{
  rowCount:number;identity:unknown;resetKey?:string;previewRows?:number;scrollRef?:RefObject<HTMLDivElement|null>;
  scrollProps?:HTMLAttributes<HTMLDivElement>;className?:string;children:(visibleCount:number)=>ReactNode;
}){
  const id=useId(),viewport=useRef<HTMLDivElement|null>(null);
  const [view,setView]=useState({identity,resetKey,expanded:false});
  const expanded=view.identity===identity&&view.resetKey===resetKey&&view.expanded;
  const head=Math.max(1,Math.min(5,previewRows));
  const visibleCount=expanded?rowCount:Math.min(head,rowCount);
  useEffect(()=>{
    setView(previous=>previous.identity===identity&&previous.resetKey===resetKey?previous:{identity,resetKey,expanded:false});
    if(viewport.current)viewport.current.scrollTop=0;
  },[identity,resetKey]);
  return <div className="bounded-table">
    <div {...scrollProps} id={id} ref={node=>{viewport.current=node;if(scrollRef)scrollRef.current=node;}}
      className={'table-scroll table-viewport '+className} tabIndex={0} role="region" aria-label="표 데이터"
      style={{...scrollProps?.style,maxHeight:expanded?'min(380px, 55dvh)':'min(260px, 45dvh)'}}>
      {children(visibleCount)}
    </div>
    {rowCount>head&&<div className="table-preview-controls"><span>{expanded?`전체 ${rowCount}행`:`앞 ${visibleCount}행 / 전체 ${rowCount}행`}</span>
      <button type="button" aria-expanded={expanded} aria-controls={id} onClick={()=>{
        if(expanded&&viewport.current)viewport.current.scrollTop=0;
        setView({identity,resetKey,expanded:!expanded});
      }}>{expanded?'접기':'펼치기'}</button>
    </div>}
  </div>;
}
