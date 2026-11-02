import { useEffect,useId,useRef,useState } from 'react';
import { ChevronLeft,ChevronRight } from 'lucide-react';
import type { WorkflowGraph } from './workflowGraph';
import { graphNeighbors,layoutWorkflow,referencedOutputs,workflowInputs,workflowSourceColors,workflowDisplayGraph } from './workflowGraph';
import { stepTitle } from './tableChanges';

export function WorkflowNavigator({graph,focus,disabled,onNavigate}:{graph:WorkflowGraph;focus:string;disabled:boolean;onNavigate:(id:string)=>void}){
  const viewport=useRef<HTMLDivElement>(null),[width,setWidth]=useState(1100);
  const marker=useId().replace(/:/g,'');
  useEffect(()=>{if(!viewport.current)return;const observer=new ResizeObserver(([entry])=>setWidth(Math.round(entry.contentRect.width)));observer.observe(viewport.current);return()=>observer.disconnect();},[]);
  const current=graph.nodes.find(n=>n.id===focus),{parents,children}=graphNeighbors(graph,focus),layout=layoutWorkflow(workflowDisplayGraph(graph),width);
  const {sources,edgeSources}=workflowSourceColors(graph);
  const routes=[...layout.routes].sort((a,b)=>Number(a.edge.from===focus||a.edge.to===focus)-Number(b.edge.from===focus||b.edge.to===focus));
  const selectedX=layout.positions.get(focus)?.x;
  useEffect(()=>{
    const container=viewport.current;
    if(!container||selectedX===undefined)return;
    // Move only this horizontal viewport; never scroll or pin the page.
    const margin=16;
    if(selectedX>=container.scrollLeft+margin&&selectedX+layout.nodeWidth<=container.scrollLeft+container.clientWidth-margin)return;
    const left=Math.max(0,Math.min(layout.width-container.clientWidth,selectedX+(layout.nodeWidth-container.clientWidth)/2));
    container.scrollTo({left,behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
  },[focus,selectedX,width,layout.width,layout.nodeWidth]);
  const name=(id:string)=>{const n=graph.nodes.find(n=>n.id===id);return n?.source?n.stage.label:`Step ${n?.order}`;};
  return <nav className="workflow-context workflow-dag" aria-label="테이블 의존 관계 Workflow" onKeyDown={e=>{const next=e.key==='ArrowLeft'?parents[0]:e.key==='ArrowRight'?children[0]:undefined;if(next&&!disabled){e.preventDefault();onNavigate(next.id);}}}>
    <div className="workflow-position"><strong>{current?.source?current.stage.label:`Step ${current?.order||''}`} <span>/ {graph.nodes.filter(n=>!n.source).length} 단계</span></strong><span className="workflow-position-label">{current&&stepTitle(current.stage)}</span></div>
    <div className="dag-neighbors"><span>연결된 입력</span>{parents.map(n=><button key={n.id} disabled={disabled} onClick={()=>onNavigate(n.id)}><ChevronLeft size={13}/>{name(n.id)}</button>)}{!parents.length&&<small>원본 입력</small>}<span className="dag-next-label">후속 단계</span>{children.map(n=><button key={n.id} disabled={disabled} onClick={()=>onNavigate(n.id)}>{name(n.id)}<ChevronRight size={13}/></button>)}{!children.length&&<small>연결된 후속 단계 없음</small>}</div>
    <div className="dag-scroll" ref={viewport}><div className="dag-canvas" style={{width:layout.width,height:layout.height}}>
      <svg width={layout.width} height={layout.height} aria-hidden="true">
        <defs><clipPath id={`${marker}-tip`}><path d="M0,0 L8,4 L0,8 Z"/></clipPath>
          {routes.map(({edge},index)=>{const colors=(edgeSources.get(edge)||[]).map(s=>s.color);if(!colors.length)colors.push('#64748b');return <marker key={index} id={`${marker}-${index}`} markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><g clipPath={`url(#${marker}-tip)`}>{colors.map((color,i)=><rect key={color} x="0" y={i*8/colors.length} width="8" height={8/colors.length} fill={color}/>)}</g></marker>;})}
        </defs>
        {routes.map(({edge,path},index)=>{const origins=edgeSources.get(edge)||[],colors=origins.length?origins.map(s=>s.color):['#64748b'];const active=edge.from===focus||edge.to===focus;return <g key={edge.from+edge.to}><title>{origins.map(s=>s.label).join(' + ')||'출처 미확인'} · 원본 입력 참조</title><path d={path} fill="none" stroke="#f0f5f2" strokeWidth="7" strokeLinejoin="round"/>{colors.map((color,i)=><path key={color} className={'dag-edge '+(active?'active ':'')+(edge.conservative?'conservative':'')} style={{stroke:color,strokeWidth:active?3.5:2.5,strokeDasharray:colors.length>1?`${edge.conservative?6:10} ${colors.length*10-(edge.conservative?6:10)}`:edge.conservative?'6 4':'none',strokeDashoffset:-i*10}} d={path} markerEnd={i===colors.length-1?`url(#${marker}-${index})`:undefined}/>)}</g>;})}
      </svg>
      {graph.nodes.map(node=>{const p=layout.positions.get(node.id);if(!p)return null;const incoming=graph.edges.filter(e=>e.to===node.id).length;const outputs=1+referencedOutputs(node.stage,graph.nodes.map(n=>n.stage)).length;return <button key={node.id} className={'dag-node '+(node.source?'source ':'')+(node.id===focus?'selected ':'')+(parents.some(p=>p.id===node.id)||children.some(c=>c.id===node.id)?'neighbor':'')} style={{left:p.x,top:p.y,width:layout.nodeWidth,height:layout.nodeHeight,...(node.source?{borderLeft:'5px solid '+sources.find(s=>s.id===node.id)?.color}:{})}} aria-current={node.id===focus?'step':undefined} disabled={disabled} onClick={()=>onNavigate(node.id)} title={`${stepTitle(node.stage)} · ${node.stage.table.stats.rows}행 × ${node.stage.table.stats.columns}열`}><span>{node.source?'INPUT':`STEP ${String(node.order).padStart(2,'0')}`}</span><strong>{stepTitle(node.stage)}</strong><small>{node.source?`${node.stage.table.stats.rows}행 · ${node.stage.table.stats.columns}열`:`입력 ${workflowInputs(node.stage).length||incoming} · 출력 ${outputs}`}{graph.unresolved[node.id]?` · 연결 미확인 ${graph.unresolved[node.id]}`:''}</small></button>;})}
    </div></div><div className="dag-source-legend" aria-label="원본 입력별 연결선 색상">{sources.map(source=><span key={source.id}><i style={{background:source.color}}/>{source.label}</span>)}{[...edgeSources.values()].some(items=>items.length>1)&&<small>합류 후에는 출처 색을 교대로 표시</small>}</div><div className="dag-legend"><span>화살표 색: 원본 입력의 참조 관계</span><span>동일 출처의 중복 우회 연결 생략</span>{graph.edges.some(e=>e.conservative)&&<span>점선: 보수적인 코드 참조</span>}<span>선택한 단계의 입력·출력을 아래에서 확인</span></div>
  </nav>;
}
