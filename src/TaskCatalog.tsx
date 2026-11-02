import { useRef, useState } from 'react';
import { FileSpreadsheet, RefreshCw, Upload, Play, Download } from 'lucide-react';
import type { TaskCandidate } from './studyTypes';
import { taskNumber } from './studyTypes';
import { TaskDiagnostics } from './TaskDiagnostics';

const template={id:'TASK-NEW',title:'수량별 주문 조회',description:'수량이 2 이상인 주문의 id와 qty를 입력 순서대로 출력하세요.',
  input_csv:'id,qty\nA,1\nB,2\nC,3',target_csv:'id,qty\nB,2\nC,3',
  initial_code:"s1 = input_df.loc[input_df['qty'] > 2].copy()\nresult = s1[['id','qty']]",
  steps:[{label:'수량 필터',statement_indices:[0],output_variable:'s1'},{label:'열 정리',statement_indices:[1],output_variable:'result'}],
  provenance:{initial_origin:'authored_mock',original_task_id:'example',actual_luna_program:false},
  researcher_notes:{error_explanation:'예제용 연구자 삽입 오류: 경계값 2 누락'}};

export function TaskCatalog({ tasks, busy, onRefresh, onImport, onPrepare, onLoad, onPublish }: {
  tasks:TaskCandidate[]; busy:boolean; onRefresh:()=>void; onImport:(data:unknown)=>Promise<void>;
  onPrepare:(id:string)=>void; onLoad:(id:string,reference:boolean)=>void; onPublish:(id:string,visible:boolean)=>void;
}) {
  const [query,setQuery]=useState(''),[message,setMessage]=useState('');
  const file=useRef<HTMLInputElement>(null);
  const shown=tasks.filter(c=>(taskNumber(c)+' '+c.id+' '+c.original_task_id+' '+c.title+' '+c.description).toLowerCase().includes(query.toLowerCase().trim()));
  const download=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(template,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='task-template.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  return <section className="task-catalog" aria-label="개발자 과제 관리">
    <header><div><span className="developer-eyebrow">TASK LIBRARY</span><h3>과제 관리</h3><p>등록 → 입력부터 체험 → 참가자 공개</p></div><div className="catalog-count"><strong>{tasks.length}</strong>개 등록<span>{tasks.filter(t=>t.enabled&&t.participant_enabled).length}개 공개</span></div></header>
    <div className="catalog-toolbar"><input aria-label="과제 검색" value={query} onChange={e=>setQuery(e.target.value)} placeholder="과제 ID·이름·설명 검색"/>
      <button className="secondary" disabled={busy} onClick={onRefresh} aria-label="과제 목록 새로고침"><RefreshCw size={14}/></button><button className="primary" disabled={busy} onClick={()=>file.current?.click()}><Upload size={14}/> 과제 JSON 추가</button>
      <input ref={file} hidden type="file" accept=".json" onChange={async e=>{const f=e.target.files?.[0];e.target.value='';if(!f)return;setMessage('');try{if(f.size>3_000_000)throw new Error('3 MB 이하 JSON 파일을 선택하세요.');await onImport(JSON.parse(await f.text()));setMessage('등록했습니다. 입력부터 체험한 뒤 참가자 공개를 켜세요.');}catch(err){setMessage((err as Error).message);}}}/>
    </div>
    {message && <p className="catalog-message" role="status">{message}</p>}
    <div className="catalog-grid">{shown.map(task=><article className="catalog-card" key={task.id}>
      <div className="catalog-card-top"><strong className="study-task-number">{taskNumber(task)}</strong><code>{task.id}</code><span className={'catalog-visibility '+(task.participant_enabled ? 'published' : '')}>{!task.enabled ? '비활성' : task.participant_enabled ? '참가자 공개' : '개발자 전용'}</span></div>
      <h4>{task.title}</h4><p>{task.description}</p><div className="catalog-meta"><span>{task.steps} Steps</span><span>{task.initial_origin==='luna_p0_observed' ? '실제 P0 저장 코드' : task.initial_origin==='authored_mock' ? '연구자 Mock' : task.initial_origin==='researcher_composite_of_observed_luna_errors'?'Luna 오류 패턴의 연구자 통제 결합':task.initial_origin==='adapted_luna_regeneration'?'Luna 재생성 코드 조정본':task.initial_origin==='luna_regeneration_observed_multifault'?'Luna 원본 관찰 코드 · 입력 바인딩':task.initial_origin==='domain_variant_of_observed_luna_multifault'?'원본 관찰 코드의 도메인 Variant':'저장 코드 · 출처 기록 확인'}</span><span>{task.trace_levels.length===task.steps && task.trace_levels.every(t=>t==='detailed') ? '상세 추적 확인' : task.trace_levels.length&&task.trace_levels.every(t=>t==='common')?'전후 표 관찰 · 상세 셀 계보 없음':'추적 범위 기록 확인'}</span></div>
      {task.screening?.pair&&<div className="catalog-meta"><span>Pair {task.screening.pair} · 도메인 {task.screening.variant}</span><span>{task.screening.level}</span>{task.screening.source_input_condition&&<span>원본 생성: {task.screening.source_input_condition==='tables-and-description'?'표·과제 설명':task.screening.source_input_condition}</span>}{task.screening.step_metrics&&<span>Step별 {task.screening.step_metrics.map(step=>step.effective_code_lines).join(' / ')}줄</span>}</div>}
      <TaskDiagnostics task={task}/>
      <div className="catalog-actions"><button className="primary" disabled={busy || !task.enabled} onClick={()=>onPrepare(task.id)}><FileSpreadsheet size={14}/> 입력부터 체험</button><button className="secondary" disabled={busy || !task.enabled} onClick={()=>onLoad(task.id,false)}><Play size={13}/> 바로 실행</button><button className="text-btn" disabled={busy || !task.has_reference_code} onClick={()=>onLoad(task.id,true)}>연구자 참조</button></div>
      <label className="catalog-publish"><input type="checkbox" checked={task.participant_enabled} disabled={busy || !task.enabled} onChange={e=>onPublish(task.id,e.target.checked)}/><span>참가자 과제 목록에 공개</span></label>
      <button className="text-btn" onClick={async()=>{const label=`${taskNumber(task)} | ${task.id} | ${task.title}`;try{await navigator.clipboard.writeText(label);setMessage(`${taskNumber(task)} 식별 정보를 복사했습니다.`);}catch{setMessage(label);}}}>피드백용 번호 복사</button>
      {task.review_notes && Object.keys(task.review_notes).length>0 && <details className="catalog-review-notes"><summary>연구자 검수 기록 · 첫 체험 후 확인</summary><p>원본 ID: {task.original_task_id} · CSV 제안 {task.review_notes['제안_Step수']}단계 / 실행 관찰 {task.steps}단계. 제안에만 있는 연산은 추가하지 않았습니다.</p>{['과제설명_확인사항','Step구성안_미계측','오류1','오류2','오류3','오류4','검수의견'].filter(key=>task.review_notes?.[key]).map(key=><p key={key}><strong>{key}</strong><br/>{task.review_notes?.[key]}</p>)}</details>}
    </article>)}</div>
    {!shown.length && <p className="catalog-empty">{tasks.length ? '검색 결과가 없습니다.' : '등록된 과제가 없습니다. JSON 파일로 추가하세요.'}</p>}
    <details className="catalog-help"><summary>과제 추가 방법과 파일 형식</summary><p>Input CSV, P0 초기 코드, Step 정보, 평가용 Target을 저장합니다. 참조 코드·오류 해설·seed는 선택 사항입니다. Output·중간 표는 실행 시 수집합니다. 같은 ID는 덮어쓰지 않으며 새 과제는 개발자 전용으로 등록됩니다.</p><p>서버 파일로 추가할 때는 TRACE_TASK_DIR 또는 .local/pilot/candidates/ 안에 ID.json을 넣으세요.</p><button className="secondary" onClick={download}><Download size={14}/> 합성 예제 템플릿 받기</button></details>
  </section>;
}
