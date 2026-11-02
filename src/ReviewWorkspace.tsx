import {useEffect,useRef,useState,type ReactNode} from 'react';
import {PythonCode} from './PythonCode';
import type {Condition,Stage} from './types';

export const conditionLabel=(condition:Condition)=>condition==='ex'?'Ex-situ':'In-situ';
export function ReviewWorkspace({condition,steps,selected,busy,explanation,title,onSelect,before,after,footer,input,target,changeLegend,version,onCondition,canSwitch,onReviewStep}:{
  condition:Condition;steps:Stage[];selected:Stage;busy:boolean;explanation:string;title:(stage:Stage)=>string;
  onSelect:(id:string)=>void;before:ReactNode;after:ReactNode;footer:ReactNode;input:ReactNode;target:ReactNode;
  changeLegend?:ReactNode;version:number;onCondition:(condition:Condition)=>void;canSwitch:boolean;
  onReviewStep?:(anchor:HTMLElement)=>void;
}){
  const [table,setTable]=useState<'input'|'target'|null>(null),dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(table)dialog.current?.showModal();else dialog.current?.close();},[table]);
  const ex=condition==='ex',position=steps.findIndex(step=>step.id===selected.id);
  return <section className="review-workspace" aria-label="변환 검수">
    <div className="review-condition-heading"><div><h1>조건 {ex?'1 · Ex-situ':'2 · In-situ'}</h1><p>{ex?'코드·설명으로 변환 검수':'테이블 변화로 변환 검수'}</p></div>
      {canSwitch&&<div className="review-condition-switch" aria-label="검수 조건">{(['ex','in-situ']as const).map(id=><button key={id} className={id===condition?'active':''} aria-pressed={id===condition} disabled={busy} onClick={()=>onCondition(id)}>{conditionLabel(id)}</button>)}</div>}</div>
    <section className="review-original-tables" aria-label="원본 Input과 Target">
      <section className="review-original-panel"><header><h2>원본 입력 <span>Input</span></h2></header>{input}</section>
      <section className="review-original-panel"><header><h2>목표 테이블 <span>Target</span></h2></header>{target}</section>
    </section>
    <div className="review-frame"><header className="review-frame-header"><strong>변환 검수</strong><span>v{version}</span><div><button className="secondary" onClick={()=>setTable('input')}>Input</button><button className="secondary" onClick={()=>setTable('target')}>Target</button></div></header>
      <div className="review-frame-body"><nav className="review-step-nav" aria-label="변환 단계">{steps.map((step,index)=><button key={step.id} disabled={busy} aria-current={step.id===selected.id?'step':undefined} className={step.id===selected.id?'active':''} onClick={()=>onSelect(step.id)}><span>{index+1}</span><strong>{title(step)}</strong></button>)}</nav>
        <section className="review-step-content" aria-label="선택 Step 상세"><h2>{ex?<>Step {position+1} · {title(selected)}</>:<button id={'review-step-title-'+selected.id} className="review-step-edit" disabled={busy} onClick={event=>onReviewStep?.(event.currentTarget)}>Step {position+1} · {title(selected)} <small>수정</small></button>}</h2><p className="review-step-explanation">{explanation}</p>
          {ex?<div className="review-step-columns review-ex-columns"><section className="review-code"><h3>변환 코드</h3><PythonCode code={selected.code}/></section><section className="review-after"><h3>중간 결과 · {selected.table.stats.rows}행</h3>{after}</section></div>:<><div className="review-step-columns review-in-columns"><section className="review-before"><h3>변환 전</h3>{before}</section><div className="review-change-arrow"><span aria-hidden="true">→</span><span>{selected.inputs&&selected.inputs.length>1?'입력 표 '+selected.inputs.length+'개':selected.input?selected.input.stats.rows+'행':'입력 크기 미확인'} → {selected.table.stats.rows}행</span></div><section className="review-after"><h3>변환 후 · {selected.table.stats.rows}행</h3>{changeLegend}{after}</section></div></>}
        </section></div>{ex&&<footer className="review-frame-footer">{footer}</footer>}</div>
    <dialog ref={dialog} className="review-source-dialog" onCancel={()=>setTable(null)} onClose={()=>setTable(null)} onClick={event=>{if(event.target===event.currentTarget)setTable(null);}}><header><h2>{table==='input'?'전체 Input':'전체 Target'}</h2><button className="secondary" onClick={()=>setTable(null)}>닫기</button></header>{table==='input'?input:target}</dialog>
  </section>;
}
