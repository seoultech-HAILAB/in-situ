import {useState} from 'react';
import type {Session} from './types';
import type {PilotApi} from './pilotTypes';

export function InitialStepJudgment({session,api,busy}:{session:Session;api:PilotApi;busy:boolean}){
  const baseline=session.review_baseline;
  const prior=session.initial_step_judgments?.filter(item=>item.condition===session.condition).at(-1);
  const [answer,setAnswer]=useState(prior?.answer||'uncertain');
  const [chosen,setChosen]=useState<string[]>(prior?.step_ids||[]);
  const [saving,setSaving]=useState(false),[message,setMessage]=useState('');
  if(!baseline||!session.run)return null;
  return <details className="initial-step-judgment"><summary>초기 파이프라인 검수 기록</summary>
    <form onSubmit={async event=>{event.preventDefault();setSaving(true);setMessage('');try{
      await api(`/sessions/${session.id}/initial-step-judgment`,{submission_id:crypto.randomUUID(),initial_run_id:baseline.run_id,
        execution_version:session.run!.id,condition:session.condition,answer,step_ids:answer==='steps'?chosen:[]});
      setMessage('응답을 저장했습니다.');
    }catch(error){setMessage((error as Error).message);}finally{setSaving(false);}}}>
      <fieldset disabled={busy||saving}><legend>수정 전 초기 실행을 기준으로 응답하세요.</legend>
        <div className="judgment-options">{([['steps','오류가 있다고 판단한 Step'],['none','오류 없음'],['uncertain','판단 어려움']]as const).map(([value,label])=><label key={value}><input type="radio" name="initial-judgment-answer" checked={answer===value} onChange={()=>{setAnswer(value);setMessage('');}}/>{label}</label>)}</div>
        {answer==='steps'&&<div className="judgment-steps">{baseline.steps.map(step=><label key={step.id}><input type="checkbox" checked={chosen.includes(step.id)} onChange={event=>{setChosen(ids=>event.target.checked?[...ids,step.id]:ids.filter(id=>id!==step.id));setMessage('');}}/>Step {step.order} · {step.label}</label>)}</div>}
        <button className="secondary" disabled={answer==='steps'&&!chosen.length}>{saving?'저장 중…':'검수 응답 저장'}</button>
      </fieldset>{message&&<p role="status">{message}</p>}
    </form>
  </details>;
}
