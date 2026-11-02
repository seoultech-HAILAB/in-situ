import { useEffect,useState } from 'react';
import { LoaderCircle,Play,Download,Upload } from 'lucide-react';
import type { ReactNode } from 'react';
import type { PilotApi } from './pilotTypes';
import type { Session,Table } from './types';
import type { PreparedTask } from './studyTypes';
import { taskNumber } from './studyTypes';

export type AssignmentState={plan_version:string;participant_id:string;total:number;completed:number;
  current:{id:string;order:number;task_id:string;condition:'ex'|'in-situ';review_number:number}|null;session_id:string|null;
  assignments:{id:string;order:number;review_number:number;condition:'ex'|'in-situ';status:'completed'|'current'|'locked'}[]};

export function AssignedTaskEntry({api,onRun,onBusy,renderTable}:{api:PilotApi;onRun:(s:Session)=>void;onBusy:(label:string)=>void;renderTable:(t:Table)=>ReactNode}) {
  const [state,setState]=useState<AssignmentState|null>(null),[task,setTask]=useState<PreparedTask|null>(null);
  const [input,setInput]=useState(''),[preview,setPreview]=useState<Table|null>(null),[uploaded,setUploaded]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{let active=true;void(async()=>{try{const s=await api<AssignmentState>('/pilot-assignment');if(!active)return;setState(s);if(s.current){const t=await api<PreparedTask>('/pilot-assignment/input');if(active){setTask(t);setInput(t.input_csv);setPreview(t.input);}}}catch(err){if(active)setError((err as Error).message);}})();return()=>{active=false;};},[]);
  const download=()=>{if(!task)return;const url=URL.createObjectURL(new Blob(['\ufeff'+task.input_csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`${task.id}-input.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  return <section className="study-entry assigned-entry"><div className="section-label"><span className="section-number">01</span><h2>배정된 과제</h2>{state&&<span className="push">{state.participant_id} · 완료 {state.completed} / {state.total}</span>}</div>
    {error&&<p className="pilot-form-error" role="alert">{error}</p>}
    {!state&&!error&&<p><LoaderCircle className="spin" size={16}/> 배정 정보를 불러오고 있습니다.</p>}
    {state&&<ol className="assigned-progress-list" aria-label="배정 과제 진행 상태">{state.assignments.map(item=><li key={item.id} className={'assigned-progress-card '+item.status} aria-current={item.status==='current'?'step':undefined}><span>{item.order}번째 · 과제 {String(item.review_number).padStart(2,'0')}</span><b>조건 {item.condition==='ex'?'Ex-situ':'In-situ'}</b>{item.status==='completed'?<button disabled>✓ 완료 · 다시 시작 불가</button>:item.status==='locked'?<button disabled>잠금 · 앞 과제 완료 후 진행</button>:<strong>{state.session_id?'진행 중 · 검수 이어가기':'현재 과제 · 아래에서 시작'}</strong>}</li>)}</ol>}
    {state&&state.total>0&&<p className="assigned-completion-note">완료는 피드백 제출 상태이며, 결과의 정답 여부를 나타내지 않습니다.</p>}
    {state&&!state.current&&<div className="assigned-finished"><h3>{state.total?'배정된 과제를 모두 마쳤습니다.':'현재 배정된 과제가 없습니다.'}</h3><p>{state.total?'실행 기록과 피드백이 저장되었습니다. 참여해 주셔서 감사합니다.':'새 과제 배정을 기다려 주세요.'}</p></div>}
    {state?.current&&task&&<><div className="assigned-position"><b>{state.current.order}번째 과제 / {state.total}개</b><span>조건 {state.current.condition==='ex'?'Ex-situ':'In-situ'} · 배정 완료</span></div><div className="study-task-intro"><span className="study-task-number">{taskNumber(task)}</span><h3>{task.title}</h3><p>{task.description}</p></div>
      <div className="study-input-tools"><span>Input {task.input.stats.rows}행 × {task.input.stats.columns}열</span><button className="secondary" disabled={busy} onClick={download}><Download size={14}/> Input CSV 받기</button>
        {!state.session_id&&<label className="secondary file-label"><Upload size={14}/> Input 업로드<input disabled={busy} type="file" accept=".csv,.tsv,.txt" onChange={async e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;setError('');try{if(file.size>1_000_000)throw new Error('1 MB 이하 Input을 사용하세요.');const bytes=await file.arrayBuffer();let text:string;try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{text=new TextDecoder('euc-kr').decode(bytes);}setPreview(await api<Table>('/preview',{text}));setInput(text);setUploaded(file.name);}catch(err){setError((err as Error).message);}}}/></label>}
      </div>{uploaded&&<p className="study-upload-label">업로드: {uploaded}</p>}<div className="study-input-preview"><div className="study-input-target-grid"><section><h4>입력 테이블 · Input</h4>{preview&&renderTable(preview)}</section><section><h4>목표 테이블 · Target <span>{task.target.stats.rows}행 × {task.target.stats.columns}열</span></h4>{renderTable(task.target)}</section></div>{Object.entries(task.sources).map(([name,t])=><section className="study-source" key={name}><h4>{name} · 추가 입력</h4>{renderTable(t)}</section>)}</div>
      <div className="study-start"><span>과제와 조건은 고정되어 있습니다. 수행 후 피드백을 남기면 다음 과제로 진행합니다.</span><button className="primary" disabled={busy} onClick={async()=>{setBusy(true);onBusy('변환 코드를 준비하고 있어요');setError('');const started=performance.now();try{const s=await api<Session>('/pilot-assignment/start',{input_csv:input});const remaining=1200-(performance.now()-started);if(remaining>0)await new Promise(resolve=>setTimeout(resolve,remaining));onRun(s);}catch(err){setError((err as Error).message);}finally{setBusy(false);onBusy('');}}}><Play size={16}/>{state.session_id?'검수 이어가기':'변환 시작'}</button></div>
    </>}
    {busy&&<div className="study-preparing" role="status"><div><LoaderCircle className="spin" size={30}/><h3>검수 화면을 준비하고 있어요</h3><p>실제 단계별 실행 결과를 구성하고 있습니다.</p><div className="study-progress"><span/></div></div></div>}
  </section>;
}
