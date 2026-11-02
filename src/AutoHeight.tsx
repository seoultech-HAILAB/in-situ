import { useLayoutEffect, useRef, type ReactNode } from 'react';

// Animate document flow to the content's natural height. No persistent height,
// maximum height, scroll container, or reserved empty space is introduced.
export function AutoHeight({ children, className = '' }: { children: ReactNode; className?: string }) {
  const outer=useRef<HTMLDivElement>(null);
  const inner=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{
    const box=outer.current, content=inner.current;
    if (!box || !content) return;
    let naturalHeight=content.offsetHeight;
    let motion: Animation | null=null;
    const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
    const stop=()=>{
      motion?.cancel(); motion=null;
      box.style.removeProperty('overflow');
    };
    const observer=new ResizeObserver(()=>{
      const next=content.offsetHeight;
      if (Math.abs(next-naturalHeight)<1) return;
      const from=motion ? box.offsetHeight : naturalHeight;
      naturalHeight=next;
      stop();
      if (reduced.matches || Math.abs(next-from)<1) return;
      box.style.overflow='clip';
      const current=box.animate([{height:`${from}px`},{height:`${next}px`}],{
        duration:320,easing:'cubic-bezier(.22,.68,.25,1)',
      });
      motion=current;
      current.onfinish=()=>{
        if (motion!==current) return;
        motion=null;
        box.style.removeProperty('overflow');
      };
    });
    observer.observe(content);
    const preferenceChanged=()=>{if(reduced.matches)stop();};
    reduced.addEventListener('change',preferenceChanged);
    return()=>{observer.disconnect();reduced.removeEventListener('change',preferenceChanged);stop();};
  },[]);
  return <div ref={outer} className={`auto-height ${className}`}><div ref={inner} className="auto-height-content">{children}</div></div>;
}
