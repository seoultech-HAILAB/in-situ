import type {ReactNode} from 'react';
import {LoaderCircle,Play} from 'lucide-react';
import type {Condition} from './types';
import type {StudyTask} from './studyTypes';
import {taskNumber} from './studyTypes';

export function WozEntry({children,tasks,taskId,busy,loading,condition,researcher,onChoose,onCondition,onStart,onReturn}:{
  children:ReactNode;tasks:(StudyTask&{initial_origin?:string})[];taskId:string;busy:boolean;loading:boolean;
  condition:Condition;researcher:boolean;onChoose:(id:string)=>void;onCondition:(condition:Condition)=>void;
  onStart:()=>void;onReturn?:()=>void;
}){
  const chosen=tasks.find(task=>task.id===taskId);
  return <section className="prototype-entry">
    <header><h2>Input과 Target으로 변환 시작</h2></header>
    <div className="prototype-entry-tools"><label>과제 <select aria-label="검수 과제" disabled={busy||loading} value={taskId} onChange={event=>onChoose(event.target.value)}>
      <option value="">{loading?'과제 불러오는 중':'과제를 선택하세요'}</option>
      {tasks.map(task=><option key={task.id} value={task.id}>{taskNumber(task)} · {task.title}</option>)}
    </select></label>{onReturn&&<button className="text-btn" disabled={busy} onClick={onReturn}>현재 실행 검수로 돌아가기</button>}</div>
    {researcher&&<small>연구자용 · 저장된 코드·Step으로 시작합니다. 초기 코드 생성 호출 없음. 자연어 수정은 LLM을 사용합니다.{chosen?.initial_origin&&` 코드 출처: ${chosen.initial_origin}`}</small>}
    {!loading&&!tasks.length&&<p>등록된 과제가 없습니다. 개발자 옵션에서 과제 코드·Step과 Input·Target을 등록하세요.</p>}
    <div className="input-grid">{children}</div>
    <div className="prototype-condition-picker" aria-label="표현 조건">{(['ex','in-situ']as const).map(id=><button key={id} disabled={busy} className={'secondary '+(condition===id?'active':'')} aria-pressed={condition===id} onClick={()=>onCondition(id)}>{id==='ex'?'조건 1 · Ex-situ':'조건 2 · In-situ'}</button>)}</div>
    <div className="study-start"><span/><button className="primary" disabled={busy||!chosen} onClick={onStart}>{busy?<LoaderCircle className="spin" size={16}/>:<Play size={16}/>} {busy?'변환 준비 중':'변환 시작'}</button></div>
  </section>;
}
