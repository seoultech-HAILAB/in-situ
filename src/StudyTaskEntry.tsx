import { FileSpreadsheet, LoaderCircle, Play, Upload, Download, ChevronLeft } from 'lucide-react';
import type { ReactNode } from 'react';
import type { PreparedTask, StudyTask } from './studyTypes';
import { taskNumber } from './studyTypes';

export function StudyTaskEntry({ tasks, selected, busy, loading, preparing, uploaded, children,
  onChoose, onUpload, onDownload, onStart, onBack, onReturn, onDeveloper, onCustom, researcher, pilot=false, condition, onCondition }: {
  tasks: StudyTask[]; selected: PreparedTask | null; busy: boolean; loading: boolean;
  preparing: 'executing' | 'presenting' | null; uploaded: string; children: ReactNode;
  onChoose: (id:string)=>void; onUpload:(file:File)=>void; onDownload:()=>void; onStart:()=>void;
  onBack:()=>void; onReturn?:()=>void; onDeveloper:()=>void; onCustom:()=>void; researcher:boolean;
  condition:'ex'|'in-situ'; onCondition:(c:'ex'|'in-situ')=>void;
  pilot?:boolean;
}) {
  return <section className="study-entry">
    <div className="section-label"><span className="section-number">01</span><h2>{selected ? '입력과 목표' : '과제 선택'}</h2>
      {onReturn && <button className="text-btn push" disabled={busy} onClick={onReturn}>검수 화면으로 돌아가기</button>}
    </div>
    {!selected ? <>
      <p className="study-entry-hint">진행할 과제를 선택한 뒤 입력 테이블을 확인하세요.</p>
      {loading && <p className="study-entry-hint"><LoaderCircle className="spin" size={15}/> 과제 목록을 불러오고 있습니다.</p>}
      <div className="study-task-grid">{tasks.map(task=><button className="study-task-card" key={task.id} disabled={busy} onClick={()=>onChoose(task.id)}>
        <span className="study-task-number">{taskNumber(task)}</span><h3>{task.title}</h3><p>{task.description}</p><strong>입력 확인 <span>→</span></strong>
      </button>)}</div>
      {!loading && !tasks.length && <div className="study-empty"><FileSpreadsheet size={28}/><p>현재 등록된 과제가 없습니다. 진행자에게 문의하세요.</p>{researcher && <button className="secondary" onClick={onDeveloper}>개발자 옵션에서 과제 관리</button>}</div>}
    </> : <>
      <button className="text-btn" disabled={busy} onClick={onBack}><ChevronLeft size={14}/> 과제 다시 선택</button>
      <div className="study-task-intro"><span className="study-task-number">{taskNumber(selected)}</span><h3>{selected.title}</h3><p>{selected.description}</p></div>
      <div className="study-input-tools"><span><FileSpreadsheet size={15}/> {selected.input.stats.rows}행 × {selected.input.stats.columns}열</span>
        <button className="secondary" disabled={busy} onClick={onDownload}><Download size={14}/> Input CSV 받기</button>
        <label className={'secondary file-label ' + (busy ? 'disabled' : '')}><Upload size={14}/> Input 업로드<input disabled={busy} type="file" accept=".csv,.tsv,.txt" onChange={e=>{const f=e.target.files?.[0];if(f)onUpload(f);e.target.value='';}}/></label>
      </div>
      {uploaded && <p className="study-upload-label">업로드: {uploaded}</p>}
      <div className="study-input-preview">{children}</div>
      <div className="study-start"><span>입력 테이블을 확인한 뒤 변환을 시작하세요.</span><button className="primary" disabled={busy} onClick={onStart}>{busy ? <LoaderCircle className="spin" size={16}/> : <Play size={16}/>} 변환 시작</button></div>
      {selected.researcherPreview && <p className="study-research-note">연구자 체험 · 저장 코드 실행 / 초기 LLM 호출 없음. 이 표시는 참가자에게 제공하지 않습니다.</p>}
    </>}
    {(researcher||pilot) && <div className="pilot-condition-picker"><strong>파일럿 표현 조건</strong>{([['ex','Ex-situ'],['in-situ','In-situ']] as const).map(([id,label])=><button key={id} className={'secondary '+(condition===id?'active':'')} aria-pressed={condition===id} disabled={busy} onClick={()=>onCondition(id)}>{label}</button>)}</div>}
    {researcher && <div className="study-research-actions"><button className="text-btn" disabled={busy} onClick={onDeveloper}>개발자 옵션 · 과제 관리</button><button className="text-btn" disabled={busy} onClick={onCustom}>Input·Target 입력 / 파이프라인 검수</button></div>}
    {preparing && <div className="study-preparing" role="status" aria-live="polite"><div><LoaderCircle className="spin" size={30}/><h3>{preparing==='presenting' ? '검수 화면을 준비하고 있어요' : '변환 코드를 준비하고 있어요'}</h3><p>입력 테이블을 바탕으로 단계별 실행 결과를 구성하고 있습니다.</p><div className="study-progress"><span/></div></div></div>}
  </section>;
}
