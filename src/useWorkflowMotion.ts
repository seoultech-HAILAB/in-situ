import { useLayoutEffect, useRef, type RefObject } from 'react';

// Keep the existing three-card window and animate its movement between layouts.
// Capture before React updates so a second click can continue from mid-animation.
export function useWorkflowMotion(rootRef: RefObject<HTMLDivElement | null>, focus: string,
  index: number, frameKey: string) {
  const before = useRef<{ key: string; index: number; cards: Map<string, DOMRect> } | null>(null);
  const animations = useRef<Animation[]>([]);
  const frame = useRef('');
  const cancel = () => { animations.current.forEach(a=>a.cancel()); animations.current=[]; };
  const prepare = () => {
    const root=rootRef.current;
    if (!root) return;
    before.current={key:frameKey,index,cards:new Map(Array.from(root.querySelectorAll<HTMLElement>('.stage-card'),
      card=>[card.id,card.getBoundingClientRect()]))};
    cancel();
  };
  useLayoutEffect(()=>{
    const root=rootRef.current;
    const snapshot=before.current;
    before.current=null;
    if (!root) { frame.current=''; return; }
    const sameFrame=frame.current===frameKey;
    frame.current=frameKey;
    const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const animate=sameFrame && snapshot?.key===frameKey && !reduced;
    const direction=index >= (snapshot?.index ?? index) ? 1 : -1;
    const bounds=root.getBoundingClientRect();
    const scale=root.offsetWidth?bounds.width/root.offsetWidth:1;
    if (animate) for (const card of root.querySelectorAll<HTMLElement>('.stage-card')) {
      const current=card.getBoundingClientRect(), prior=snapshot.cards.get(card.id);
      const offset=(prior ? prior.left-current.left : direction*Math.min(bounds.width*.4,520))/scale;
      if (Math.abs(offset)<1) continue;
      animations.current.push(card.animate([
        {transform:`translateX(${offset}px)`,opacity:prior ? 1 : .35},
        {transform:'translateX(0)',opacity:1},
      ],{duration:300,easing:'cubic-bezier(.22,.68,.25,1)'}));
    }
    return cancel;
  },[focus,frameKey]);
  return prepare;
}
