import { useEffect,useRef,useState } from 'react';
import { MessageSquare,X } from 'lucide-react';
import type { Session } from './types';
import type { PilotApi } from './pilotTypes';
import { taskNumber } from './studyTypes';

const questions=[['task_clarity','과제 설명이 명확했다'],['navigation_ease','필요한 단계와 데이터를 찾기 쉬웠다'],['change_understanding','각 단계의 데이터 변화를 이해하기 쉬웠다']] as const;
const issueOptions=[['ambiguous_requirement','과제 설명이 모호함'],['insufficient_input','입력에 필요한 정보가 없음'],['target_inconsistent','Target의 근거·일관성이 의심됨'],['ui_problem','화면·탐색이 불편함'],['revision_problem','수정·실행이 잘되지 않음'],['other','기타']] as const;

export function PilotFeedback({session,api,busy,onNext}:{session:Session;api:PilotApi;busy:boolean;onNext?:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const [snapshot,setSnapshot]=useState<{submission_id:string;execution_version:string|null;condition:Session['condition']}|null>(null);
  const [ratings,setRatings]=useState<Record<string,string>>({}),[outcome,setOutcome]=useState(''),[comments,setComments]=useState('');
  const [issueTypes,setIssueTypes]=useState<string[]>([]);
  const [saving,setSaving]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(!!session.feedbacks?.length);
  useEffect(()=>{if(snapshot)dialog.current?.showModal();else dialog.current?.close();},[snapshot]);
  const label=taskNumber({id:session.task_id,review_number:session.task_display?.review_number});
  return <section className="pilot-feedback-entry"><div><strong>과제·화면 피드백</strong><p>{saved?'저장했습니다. 최종 확정과 별도로 기록됩니다.':'과제 설명·Input·Target의 문제와 사용 중 불편을 남겨주세요. 약 10분간 막혔다면 중단 후 제출해도 됩니다.'}</p></div>
    <button className="secondary" disabled={busy} onClick={()=>{setError('');setSnapshot({submission_id:crypto.randomUUID(),execution_version:session.run?.id||null,condition:session.condition});}}><MessageSquare size={15}/>{saved?'피드백 추가':'피드백 남기기'}</button>
    {saved&&onNext&&<button className="primary" disabled={busy} onClick={onNext}>다음 배정 과제로</button>}
    <dialog ref={dialog} className="pilot-feedback-dialog" onCancel={e=>{if(saving)e.preventDefault();else setSnapshot(null);}} onClick={e=>{if(e.target===e.currentTarget&&!saving)setSnapshot(null);}}>
      <form onSubmit={async e=>{e.preventDefault();if(!snapshot)return;setSaving(true);setError('');try{await api(`/sessions/${session.id}/feedback`,{...snapshot,...Object.fromEntries(questions.map(([id])=>[id,ratings[id]?Number(ratings[id]):null])),outcome,comments,issue_types:issueTypes});setSaved(true);setSnapshot(null);}catch(err){setError((err as Error).message);}finally{setSaving(false);}}}>
        <div className="drawer-header"><h2>{label} · {session.condition==='ex'?'Ex-situ':'In-situ'} 피드백</h2><button className="icon-button" type="button" aria-label="피드백 닫기" disabled={saving} onClick={()=>setSnapshot(null)}><X size={18}/></button></div>
        <p className="pilot-form-hint">1 전혀 그렇지 않다 — 5 매우 그렇다 · 경험하지 않은 항목은 해당 없음</p>
        {questions.map(([id,text])=><fieldset key={id} disabled={saving}><legend>{text}</legend><div className="pilot-rating">{['1','2','3','4','5',''].map(value=><label key={value||'na'}><input type="radio" name={id} value={value} checked={(ratings[id]??'')===value} onChange={()=>setRatings({...ratings,[id]:value})}/>{value||'해당 없음'}</label>)}</div></fieldset>)}
        <label className="pilot-field-label" htmlFor="pilot-outcome">이번 수행 상태</label><select id="pilot-outcome" required value={outcome} disabled={saving} onChange={e=>setOutcome(e.target.value)}><option value="" disabled>선택하세요</option><option value="revised">필요한 수정을 마쳤다고 생각함</option><option value="found_not_revised">오류를 발견했지만 수정을 완료하지 못함</option><option value="uncertain">오류가 있는지 판단하기 어려웠음</option><option value="task_issue">과제 설명·입력·Target 자체에 문제가 있다고 생각함</option><option value="time_limit">약 10분간 이해·진행이 어려워 중단함</option><option value="blocked">실행·화면·수정 기능 문제로 중단함</option></select>
        <fieldset disabled={saving} className="pilot-issue-types"><legend>발견한 문제 <span>복수 선택 · 선택 사항</span></legend>{issueOptions.map(([id,text])=><label key={id}><input type="checkbox" checked={issueTypes.includes(id)} onChange={e=>setIssueTypes(types=>e.target.checked?[...types,id]:types.filter(type=>type!==id))}/>{text}</label>)}</fieldset>
        <label className="pilot-field-label" htmlFor="pilot-comments">과제·데이터 문제 / 막힌 Step / UI 불편과 개선 의견 <span>선택</span></label><textarea id="pilot-comments" value={comments} maxLength={3000} disabled={saving} onChange={e=>setComments(e.target.value)} placeholder="어느 표·열·값에서 왜 판단이 어려웠는지, Target에 필요한 정보가 Input에 있는지, 불편한 조작을 구체적으로 남겨주세요."/>
        <p className="pilot-form-hint">과제가 불명확하거나 필요한 정보가 없다면 억지로 수정·확정하지 말고 그 근거를 남겨주세요. 중단 피드백도 다음 과제로 진행할 수 있습니다.</p>
        {error&&<p className="pilot-form-error" role="alert">{error}</p>}<div className="pilot-form-actions"><button type="button" className="secondary" disabled={saving} onClick={()=>setSnapshot(null)}>닫기</button><button className="primary" disabled={saving||!outcome}>{saving?'저장 중…':'피드백 저장'}</button></div>
      </form>
    </dialog>
  </section>;
}
