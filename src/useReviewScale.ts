import { useEffect,useState } from 'react';

type DisplayMetrics={screenWidth:number;screenHeight:number;viewportWidth:number;outerWidth:number;finePointer:boolean};

// Screen size is a heuristic for laptop-sized displays, not hardware detection.
export function laptopReviewScale(metrics:DisplayMetrics):1|0.67 {
  const {screenWidth,screenHeight,viewportWidth,outerWidth,finePointer}=metrics;
  if(!finePointer||screenWidth<1024||screenWidth>1920||screenHeight<600||screenHeight>1200||viewportWidth<960)return 1;
  // Browser zoom changes the viewport relative to the outer window. Respect it
  // rather than multiplying a manual 67% (or accessibility zoom) by another 67%.
  const browserScale=outerWidth/viewportWidth;
  if(!Number.isFinite(browserScale)||browserScale<.92||browserScale>1.08)return 1;
  return .67;
}

function currentScale(){
  return laptopReviewScale({screenWidth:window.screen.width,screenHeight:window.screen.height,
    viewportWidth:window.innerWidth,outerWidth:window.outerWidth,
    finePointer:window.matchMedia('(hover: hover) and (pointer: fine)').matches});
}

export function useReviewScale(){
  const [scale,setScale]=useState(currentScale);
  useEffect(()=>{
    const update=()=>setScale(currentScale());
    const pointer=window.matchMedia('(hover: hover) and (pointer: fine)');
    window.addEventListener('resize',update);window.addEventListener('focus',update);
    pointer.addEventListener('change',update);update();
    return()=>{window.removeEventListener('resize',update);window.removeEventListener('focus',update);pointer.removeEventListener('change',update);};
  },[]);
  return scale;
}
