import type { ReactNode } from 'react';
import { LoaderCircle,Play,Table2 } from 'lucide-react';

export function PrototypeEntry({children,busy,condition,onCondition,onExample,onStart,onReturn}:{
  children:ReactNode;busy:boolean;condition:'ex'|'in-situ';onCondition:(condition:'ex'|'in-situ')=>void;
  onExample:()=>void;onStart:()=>void;onReturn?:()=>void;
}){
  return <section className="prototype-entry">
    <header><span className="prototype-badge">연구 프로토타입</span><h2>Input과 Target으로 변환 생성</h2>
      <p>전체 Input과 현재 Input의 정확한 기대 출력인 Target을 입력하세요.</p>
      <small>확인용 예제는 기능 검증 자료이며 본실험 과제로 선정된 자료가 아닙니다.</small></header>
    <div className="prototype-entry-tools"><button className="secondary" disabled={busy} onClick={onExample}><Table2 size={15}/> 확인용 표 불러오기</button>
      {onReturn&&<button className="text-btn" disabled={busy} onClick={onReturn}>현재 실행 검수로 돌아가기</button>}</div>
    <div className="input-grid">{children}</div>
    <div className="prototype-condition-picker" aria-label="프로토타입 표현 조건">{(['ex','in-situ'] as const).map(id=><button key={id} className={'secondary '+(id===condition?'active':'')} aria-pressed={id===condition} disabled={busy} onClick={()=>onCondition(id)}>{id==='ex'?'조건 1 · Ex-situ':'조건 2 · In-situ'}</button>)}</div>
    <div className="study-start"><span>같은 초기 코드·Step·실행 결과를 두 표현으로 검수합니다.</span><button className="primary" disabled={busy} onClick={onStart}>{busy?<LoaderCircle className="spin" size={16}/>:<Play size={16}/>} {busy?'생성·실행 중':'LLM 코드·Step 생성'}</button></div>
  </section>;
}
