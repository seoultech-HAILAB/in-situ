import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {ReviewComment,type CommentReceipt} from './ReviewComment';
import {SelectionAction} from './SelectionAction';
import { PythonCode } from './PythonCode';
import { AutoHeight } from './AutoHeight';
import { WozEntry } from './WozEntry';
import {InitialStepJudgment} from './InitialStepJudgment';
import {TableViewport} from './TableViewport';
import {ReviewWorkspace,conditionLabel} from './ReviewWorkspace';
import {reviewGroups,groupColor,groupBorder} from './reviewGroups';
import { StudyTaskEntry } from './StudyTaskEntry';
import { TaskCatalog } from './TaskCatalog';
import { PilotFeedback } from './PilotFeedback';
import { PilotRecords } from './PilotRecords';
import { AssignedTaskEntry,type AssignmentState } from './AssignedTaskEntry';
import type { PreparedTask, StudyTask, TaskCandidate } from './studyTypes';
import { taskNumber } from './studyTypes';
import { ArrowRight, ArrowUpRight, Braces, Check, ChevronDown, CircleHelp, Columns3, Download, FileSpreadsheet, Filter, FlaskConical, GitBranch, Layers3, LoaderCircle, MessageSquare, Play, Plus, RotateCcw, Settings2, Sparkles, Table2, Upload, X } from 'lucide-react';
import type { Condition, CellValue, Ref, ReviewTarget, Run, Selection, Session, Stage, Table } from './types';
import { useTableDrag } from './useTableDrag';
import { useReviewScale } from './useReviewScale';
import { buildWorkflowGraph,ownerOf,referencedOutputs,workflowInputs,workflowReviewWindow,reviewRun } from './workflowGraph';
import {ColumnOrigin,ColumnOriginDetails} from './ColumnOrigin';
import {selectedCells,pointKey,combineSelection} from './tableSelection';
import { cellKey, stepTitle, focusWindow, tableChanges, type TableChanges } from './tableChanges';
import './styles.css';

const explanationsReady=(run:Run)=>run.explanation_status==='ready'&&run.stages.slice(1).every(stage=>stage.column_explanations!==undefined&&(stage.operations||[]).every(op=>op.column_explanations!==undefined));
async function api<T>(path: string, body?: unknown): Promise<T> {
  const headers = {'Content-Type':'application/json','X-Trace-View':new URLSearchParams(location.search).get('research') === '1' ? 'researcher' : 'participant'};
  const res = await fetch('/api' + path, body === undefined ? {headers} : { method: 'POST', headers, body: JSON.stringify(body) });
  if (!res.ok) { let data; try { data = await res.json(); } catch { throw new Error(`서버 오류 (${res.status})`); } throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)); }
  let data=await res.json();
  if(!path.endsWith('/explanations')&&data?.run&&Array.isArray(data.runs)&&['ex','in-situ'].includes(data.condition)&&!explanationsReady(data.run)){
    try{
      const described=await fetch(`/api/sessions/${data.id}/explanations`,{method:'POST',headers,body:JSON.stringify({run_id:data.run.id})});
      if(described.ok)data=await described.json();
      else if(described.status===409){const latest=await fetch(`/api/sessions/${data.id}`,{headers});if(latest.ok)data=await latest.json();}
      else{data.run.explanation_status='failed';data.run.explanation_error='자연어 설명을 불러오지 못했습니다. 다시 시도하세요.';}
    }catch{data.run.explanation_status='failed';data.run.explanation_error='설명 API에 연결하지 못했습니다. 다시 시도하세요.';}
  }
  return data;
}
const exTitle=(stage:Stage)=>stage.nl_explanation?.title||stepTitle(stage);
const exText=(stage:Stage)=>stage.nl_explanation?.text||'자연어 설명을 준비하지 못했습니다. 설명을 다시 불러와 주세요.';
const fmt = (v: CellValue | undefined) => v == null ? '∅' : Array.isArray(v) ? JSON.stringify(v) : typeof v === 'number' ? (v !== 0 && Math.abs(v) < 0.000001 ? String(v) : v.toLocaleString('ko-KR', { maximumFractionDigits: 20 })) : String(v);
const opIcon = (kind: string) => kind === 'filter' ? <Filter size={15}/> : kind === 'derive' ? <Plus size={15}/> : kind === 'aggregate' ? <span className="sigma">Σ</span> : <Table2 size={15}/>;
type AnchoredComment = { target: ReviewTarget; anchor: HTMLElement; base_run_id: string; session_id: string;
  version: number; title: string; preview: string; scope: 'step' | 'pipeline'; error: string; receipt?: CommentReceipt };
const draftKey = (c: AnchoredComment) => JSON.stringify([c.session_id, c.base_run_id, c.target.step_id,
  c.target.cells,c.target.operation_id,c.target.table_role,c.target.input_ref, c.target.kind, c.target.row_id, c.target.column, c.target.row_ids, c.target.columns, !!c.target.removed]);

function DataTable({ data, stage, selection, onSelect, onSelectRow, onSelectColumn, onSelectRange, reviewTarget, selectionDisabled = false, refs = [], keyRefs = [], removed = false, previous, delta, inputDelta, groupRows, groupCells, tableRole='output', inputRef, compact = false, integrated = false, plain = false, limit }: {
  data: Table; stage?: Stage; selection?: Selection | null; onSelect?: (r: string, c: string, anchor: HTMLElement,additive?:boolean) => void; onSelectRow?: (r: string, anchor: HTMLElement,additive?:boolean) => void; onSelectColumn?: (c: string, anchor: HTMLElement,additive?:boolean) => void; onSelectRange?: (target: ReviewTarget, anchor: HTMLElement, final: boolean) => void; reviewTarget?: ReviewTarget | null; selectionDisabled?: boolean; refs?: Ref[]; keyRefs?: Ref[]; removed?: boolean; previous?: Stage; delta?: TableChanges | null; inputDelta?:TableChanges|null; groupRows?:Record<string,number>;groupCells?:Record<string,number>;tableRole?:'input'|'output';inputRef?:string;compact?: boolean; integrated?: boolean; plain?: boolean; limit?: number;
}) {
  const isRelated = (r: string, c: string, sources: Ref[]) => {
    const own = stage ? stage.lineage[r]?.[c] || [] : [{ row_id: r, column: c }];
    return own.some(v => sources.some(s => (s.table_id||'input')===(v.table_id||'input')&&s.row_id === v.row_id && s.column === v.column));
  };
  const tableRoot = useRef<HTMLDivElement>(null);
  const drag = useTableDrag(tableRoot, data, stage, removed, selectionDisabled, onSelectRange,{table_role:tableRole,...(inputRef?{input_ref:inputRef}:{})},reviewTarget);
  const oldRows = previous?.trace_level === 'detailed' && stage?.trace_level === 'detailed' ? previous.table.rows : undefined;
  const inputRows = useMemo(()=>new Map(stage?.input?.rows.map(r=>[r.id,r]) || []),[stage?.input]);
  const targetHere = (reviewTarget?.table_role||'output')===tableRole&&reviewTarget?.input_ref===inputRef&&reviewTarget?.step_id === stage?.id && reviewTarget?.operation_id === stage?.view_operation_id && !!reviewTarget?.removed === removed;
  const picked=useMemo(()=>new Set(targetHere?selectedCells(reviewTarget,data).map(cell=>pointKey(cell.row_id,cell.column)):[]),[targetHere,reviewTarget,data]);
  return <TableViewport rowCount={data.rows.length} identity={data} resetKey={`${stage?.execution_version||''}:${stage?.id||''}:${tableRole}:${inputRef||''}:${removed}`} previewRows={limit} scrollRef={tableRoot} scrollProps={{onPointerDown:drag,onMouseDown:(onSelect || onSelectRow || onSelectColumn) ? e=>{if ((e.target as HTMLElement).closest('button')) e.preventDefault();} : undefined,onDragStart:onSelectRange ? e=>e.preventDefault() : undefined}} className={(compact ? 'compact ' : '') + (onSelectRange ? 'drag-selectable ' : '')}>{visibleCount=><><table><thead><tr><th className="row-number">#</th>{data.columns.map((c,j) => {
    const added=!!delta?.addedColumns.includes(c);
    const p = stage?.params;
    const formula = integrated && p?.formulas?.[c];
    const agg = integrated && p?.aggregations?.[c];
    const key = integrated && p?.keys?.includes(c);
    const filter = integrated && stage?.kind === 'filter' && p?.columns?.includes(c);
    return <th key={c} tabIndex={onSelectColumn&&!selectionDisabled?0:undefined} onClick={onSelectColumn?event=>{if(!selectionDisabled){event.stopPropagation();onSelectColumn(c,event.currentTarget,event.ctrlKey||event.metaKey);}}:undefined} onKeyDown={onSelectColumn?event=>{if(event.target===event.currentTarget&&!selectionDisabled&&(event.key==='Enter'||event.key===' ')){event.preventDefault();onSelectColumn(c,event.currentTarget,event.ctrlKey||event.metaKey);}}:undefined} data-drag-kind={onSelectRange ? 'column' : undefined} data-ri={-1} data-ci={j} className={[formula || agg ? 'derived-head' : key ? 'key-head' : filter ? 'filter-head' : '',targetHere&&((reviewTarget?.kind==='column'&&reviewTarget.column===c)||(reviewTarget?.kind==='columns'&&reviewTarget.columns?.includes(c)))&&'review-selected-column-head',delta?.addedColumns.includes(c) && 'step-added-column',inputDelta?.removedColumns.includes(c)&&'step-removed-input-column'].filter(Boolean).join(' ')} title={plain ? c : data.stats.fields[c] ? `${data.stats.fields[c].dtype} · 결측 ${data.stats.fields[c].missing}${data.stats.fields[c].min != null ? ` · 관찰 최소 ${data.stats.fields[c].min} · 관찰 최대 ${data.stats.fields[c].max}` : ''}` : c}>
      {added&&stage?<ColumnOrigin key={stage.execution_version+':'+stage.id+':'+c} stage={stage} column={c}/>:<span className="column-name">{key&&<span className="key-symbol">⌘</span>}{filter&&<Filter size={11}/>} {c}{formula&&<span className="new-col">ƒ</span>}</span>}
      {!added&&(formula||agg) && <small>{stage?.column_explanations?.[c]||'설명 미제공'}</small>}
    </th>;
  })}</tr></thead><tbody>{data.rows.slice(0, visibleCount).map((r, i) => {
    const isNew = !removed && oldRows && !oldRows.some(old => old.id === r.id);
    const priorDecision = previous?.params.decisions?.[r.id];
    const inclusionChanged = priorDecision && stage?.params.decisions?.[r.id] && priorDecision.kept !== stage.params.decisions[r.id].kept;
    const removedByStep=integrated&&inputDelta?.rowIdentity&&inputDelta.removedRows.some(row=>row.id===r.id);
    return <tr key={r.id} title={removedByStep?'선택 Step에서 제외된 입력 행':undefined} className={(removed ? 'excluded ' : '') + (removedByStep?'step-removed-input-row ':'') + (isNew ? 'revision-new-row ' : '') + (inclusionChanged ? 'inclusion-changed ' : '') + (delta?.changedRows.has(r.id) ? 'step-changed-row ' : '') + (delta?.movedRows.has(r.id) ? 'step-moved-row' : '')}>
      <td className="row-number" data-drag-kind={onSelectRange ? 'row' : undefined} data-ri={i} data-ci={-1} title={r.id + (inclusionChanged ? ` · 이전 ${priorDecision.kept ? '유지' : '제외'} → 현재 ${removed ? '제외' : '유지'}` : '')}>{onSelectRow ? <button className="row-select-button" disabled={selectionDisabled} aria-label={`${stage?.label} 행 선택 ${r.id}${removed ? ' 제외된 입력' : ''}`} onClick={e => { e.stopPropagation(); onSelectRow(r.id, e.currentTarget,e.ctrlKey||e.metaKey); }}>{inclusionChanged ? 'Δ' : removed ? '−' : i + 1}</button> : inclusionChanged ? 'Δ' : removed ? '−' : i + 1}</td>{data.columns.map((c,j) => {
        const selected = (selection?.table_role||'output')===tableRole&&selection?.input_ref===inputRef&&selection?.step === stage?.id && selection?.row === r.id && selection?.column === c && !!selection?.removed === removed;
        const selectedRange = targetHere&&picked.has(pointKey(r.id,c));

        const cellSources=(removed?stage?.removed_lineage:stage?.lineage)?.[r.id]?.[c];
        const related = integrated && refs.length > 0 && (stage ? !!cellSources?.some(source=>refs.some(ref=>(ref.table_id||'input')===(source.table_id||'input')&&ref.row_id===source.row_id&&ref.column===source.column)) : isRelated(r.id,c,refs));
        const keyRelated = integrated && keyRefs.length > 0 && isRelated(r.id, c, keyRefs);
        const oldRow = oldRows?.find(old => old.id === r.id);
        const changed = oldRow && JSON.stringify(oldRow.values[c]) !== JSON.stringify(r.values[c]);
        const stepChanged = delta?.changedCells.has(cellKey(r.id,c));
        const changeTitle = stepChanged ? `Step 입력: ${fmt(inputRows.get(r.id)?.values[c])} → 출력: ${fmt(r.values[c])}` : delta?.addedColumns.includes(c) ? 'Step에서 추가된 열' : inputDelta?.changedCells.has(cellKey(r.id,c))?'선택 Step에서 값이 바뀐 입력 셀':undefined;
        const group=groupCells?.[cellKey(r.id,c)]??groupRows?.[r.id];
        return <td key={c} tabIndex={onSelect&&!selectionDisabled?0:undefined} onClick={onSelect?event=>{if(!selectionDisabled){event.stopPropagation();onSelect(r.id,c,event.currentTarget,event.ctrlKey||event.metaKey);}}:undefined} onKeyDown={onSelect?event=>{if(!selectionDisabled&&(event.key==='Enter'||event.key===' ')){event.preventDefault();event.stopPropagation();onSelect(r.id,c,event.currentTarget,event.ctrlKey||event.metaKey);}}:undefined} title={group===undefined?changeTitle:`G${group+1} · 확인된 집계 그룹${changeTitle?' · '+changeTitle:''}`} style={{...(group===undefined?{}:{'--group-color':groupColor(group),'--group-border':groupBorder(group)}),...(selectedRange?{'--pick-top':i>0&&picked.has(pointKey(data.rows[i-1].id,c))?'0px':'2px','--pick-bottom':i<data.rows.length-1&&picked.has(pointKey(data.rows[i+1].id,c))?'0px':'2px','--pick-left':j>0&&picked.has(pointKey(r.id,data.columns[j-1]))?'0px':'2px','--pick-right':j<data.columns.length-1&&picked.has(pointKey(r.id,data.columns[j+1]))?'0px':'2px'}:{})} as React.CSSProperties} data-drag-kind={onSelectRange ? 'cell' : undefined} data-ri={i} data-ci={j} className={[group!==undefined&&'review-group-cell',groupRows?.[r.id]!==undefined&&j===0&&'review-group-start',selected && 'selected-cell', selectedRange && 'comment-selected-range', related && 'source-cell', keyRelated && 'key-cell', changed && 'revision-changed-cell', stepChanged && 'step-changed-cell', inputDelta?.changedCells.has(cellKey(r.id,c))&&'step-changed-input-cell', delta?.addedColumns.includes(c) && 'step-added-cell', typeof r.values[c] === 'number' && 'numeric'].filter(Boolean).join(' ')}>
          <span>{fmt(r.values[c])}</span>
        </td>;
      })}
    </tr>;
  })}</tbody></table>{!data.rows.length && <div className="empty-table">0행</div>}</>}</TableViewport>;
}

function UploadPanel({ title, english, text, setText, preview, onPreview, onFile }: { title: string; english: string; text: string; setText: (s: string) => void; preview: Table | null; onPreview: () => void; onFile: (file: File) => void }) {
  return <section className="upload-panel"><div className="panel-heading"><div className="panel-icon"><Table2 size={17}/></div><h3>{title} <span>{english}</span></h3><label className="text-btn file-label"><Upload size={13}/> CSV 업로드<input type="file" accept=".csv,.tsv,.txt" onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ''; }}/></label></div>
    <textarea aria-label={`${title} 붙여넣기`} className="csv-input" value={text} onChange={e => setText(e.target.value)} placeholder={'열 이름을 포함한 CSV 또는 탭 구분 표를 붙여넣으세요.\n예: 지역,수량,단가\n서울,2,10000'}/>
    <div className="input-bottom"><span>CSV · TSV · 최대 500행</span><button className="text-btn" disabled={!text.trim()} onClick={onPreview}>미리보기 <ArrowUpRight size={13}/></button></div>
    {preview && <DataTable data={preview} compact limit={4}/>}
  </section>;
}

function App() {
  const reviewScale=useReviewScale();
  const prototypeWorkspace=new URLSearchParams(location.search).get('workspace')!=='tasks';
  const [session, setSession] = useState<Session | null>(null);
  const [health, setHealth] = useState<{ api_configured: boolean; model: string; access_role: string; team_mode: boolean;participant_id:string|null;pilot_account:boolean } | null>(null);
  const [developerTab,setDeveloperTab]=useState<'tasks'|'logs'>('tasks');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [draft, setDraft] = useState(false);
  const [input, setInput] = useState(''), [target, setTarget] = useState(''), [requirements, setRequirements] = useState('');
  const [inputPreview, setInputPreview] = useState<Table | null>(null), [targetPreview, setTargetPreview] = useState<Table | null>(null);
  const [request, setRequest] = useState('');
  const [scope, setScope] = useState<'step' | 'pipeline'>('step');
  const [taskCandidates,setTaskCandidates] = useState<TaskCandidate[]>([]);
  const [publicTasks,setPublicTasks] = useState<StudyTask[]>([]);
  const [wozTasks,setWozTasks]=useState<(StudyTask&{initial_origin?:string})[]>([]);
  const [wozTaskId,setWozTaskId]=useState('');
  const [wozLoading,setWozLoading]=useState(true);
  const [tasksLoading,setTasksLoading] = useState(true);
  const [preparedTask,setPreparedTask] = useState<PreparedTask | null>(null);
  const [studyInputCsv,setStudyInputCsv] = useState('');
  const [studyInputTable,setStudyInputTable] = useState<Table | null>(null);
  const [studyUploadName,setStudyUploadName] = useState('');
  const [entryOpen,setEntryOpen] = useState(false);
  const [preparing,setPreparing] = useState<'executing' | 'presenting' | null>(null);
  const [researchMode,setResearchMode] = useState(new URLSearchParams(location.search).get('research')==='1');
  const [activeOps, setActiveOps] = useState<Record<string,string>>({});
  const [extraSources, setExtraSources] = useState<Record<string,{text:string; table:Table}>>({});
  const [focus, setFocusedStep] = useState('s1');
  const [viewStep, setViewStep] = useState('s1');
  const [selection, setSelection] = useState<Selection | null>(null);
  const [comment, setComment] = useState<AnchoredComment | null>(null);
  const [pickedTarget,setPickedTarget]=useState<ReviewTarget|null>(null);
  const pickedRef=useRef<ReviewTarget|null>(null);
  useEffect(()=>{pickedRef.current=null;setPickedTarget(null);},[session?.id,session?.run?.id,viewStep,session?.condition]);
  const [commentEditorOpen,setCommentEditorOpen]=useState(false);
  const [dragSelecting,setDragSelecting]=useState(false);
  const [commentDrafts,setCommentDrafts]=useState<Record<string,string>>({});
  const [settings, setSettings] = useState(false);
  const [condition, setCondition] = useState<Condition>('in-situ');
  const [taskId, setTaskId] = useState('custom-task');
  const [researchCode, setResearchCode] = useState('');
  const [researchSteps,setResearchSteps] = useState('');
  const [structureWithLLM,setStructureWithLLM] = useState(false);
  const [replayFile, setReplayFile] = useState<Record<string, unknown> | null>(null);
  const [replayIndex, setReplayIndex] = useState(0);
  const [expandedData, setExpandedData] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const canResearch = !!health && health.access_role !== 'participant';
  const researcher = researchMode && canResearch;
  useEffect(() => {
    if (researcher) api<TaskCandidate[]>('/task-candidates?full=true').then(setTaskCandidates).catch(e=>setError((e as Error).message));
  },[researcher]);
  useEffect(()=>{api<StudyTask[]>('/study-tasks').then(setPublicTasks).catch(e=>setError('과제 목록을 불러오지 못했습니다. 서버를 확인하세요. '+(e as Error).message)).finally(()=>setTasksLoading(false));},[]);
  useEffect(()=>{if(!health||health.pilot_account)return;api<StudyTask[]>('/woz-tasks').then(setWozTasks).catch(e=>setError((e as Error).message)).finally(()=>setWozLoading(false));},[health?.pilot_account,health?.access_role]);
  const run=useMemo(()=>reviewRun(session?.run),[session?.run]);
  const observedOutput=session?.run?.stages.at(-1)?.table;
  const isPrototype=session?.study_mode==='prototype-v1';
  const entryVisible = entryOpen || (!session && !draft);
  const cond = entryVisible ? condition : session?.condition || condition;
  const previous = session?.runs.find(r => r.id === run?.parent_run_id);
  const isEx = cond === 'ex';
  const workflowGraph=useMemo(()=>buildWorkflowGraph(run?.stages||[],session?.sources||{}),[run,session?.sources]);
  const focusedReview = workflowGraph.nodes.find(n=>n.id===focus)?.stage || run?.stages[1];
  const focusIndex = Math.max(0, run?.stages.findIndex(st=>st.id === focus) ?? 0);
  const viewIndex = Math.max(0, run?.stages.findIndex(st=>st.id === viewStep) ?? 0);
  const displayedStage=workflowGraph.nodes.find(n=>n.id===viewStep)?.stage||focusedReview;

  function setFocus(id: string) {
    setFocusedStep(id);
  }
  const showEditor = (!session || draft) && !entryVisible;
  useEffect(() => {
    if (comment && (isEx || showEditor || entryVisible || settings || comment.session_id !== session?.id ||
      (comment.base_run_id !== run?.id && comment.receipt?.run_id !== run?.id))) setComment(null);
  }, [cond, showEditor, entryVisible, settings, session?.id, run?.id, comment]);
  const runLookup = new Map((session?.runs || []).map(r => [r.id, r]));
  const commentRuns: Run[] = [];
  const visitedRuns = new Set<string>();
  let ancestor = run;
  while (ancestor && !visitedRuns.has(ancestor.id)) {
    visitedRuns.add(ancestor.id);
    if (ancestor.review_comment) commentRuns.unshift(ancestor);
    ancestor = ancestor.parent_run_id ? runLookup.get(ancestor.parent_run_id) : undefined;
  }

  function accept(s: Session) {
    if(s.id!==session?.id)setExpandedData(true);
    const acceptedSteps=reviewRun(s.run)?.stages||[];
    const acceptedDefault=acceptedSteps.find(stage=>stage.kind!=='input')?.id||'input';
    setSession(s); localStorage.setItem(s.study_mode==='woz-v1'?'trace-woz-session':s.study_mode==='prototype-v1'?'trace-prototype-session':s.pilot_account&&s.participant_id ? `trace-session:${s.participant_id}` : 'trace-session', s.id); setCondition(s.condition); setDraft(false); setEntryOpen(false);
    const url = new URL(location.href); url.searchParams.set('session',s.id); history.replaceState(null,'',url);
    setResearchCode(s.run?.code || '');
    if (s.run?.id !== run?.id) {setActiveOps({});setSelection(null);}
    if ((focus === 'input') || !acceptedSteps.some(st => st.id === focus)) setFocus(acceptedDefault);
    if (!acceptedSteps.some(st => st.id === viewStep)) setViewStep(acceptedDefault);
    if (s.condition !== 'in-situ') setSelection(null);
    else if (selection&&s.run?.id===run?.id) {
      if (selection.operation_id && s.run?.id !== run?.id) { setSelection(null); return; }
      const stage = s.run?.stages.find(st => st.id === selection.step && st.table.columns.includes(selection.column));
      if (stage?.table.rows.some(r => r.id === selection.row)) setSelection({ ...selection, removed: false });
      else if (stage?.removed?.rows.some(r => r.id === selection.row)) setSelection({ ...selection, removed: true });
      else setSelection(null);
    }
  }
  async function perform(label: string, f: () => Promise<void>) { setBusy(label); setError(''); try { await f(); } catch (e) { setError((e as Error).message); } finally { setBusy(''); } }
  function openDeveloper() {
    if (!canResearch) return;
    const url=new URL(location.href);url.searchParams.set('research','1');history.replaceState(null,'',url);
    setResearchMode(true);setSettings(true);
    if(session)api<Session>(`/sessions/${session.id}`).then(s=>{setSession(s);setResearchCode(s.run?.code || '');}).catch(e=>setError((e as Error).message));
  }
  async function refreshTaskLibrary() {
    setTasksLoading(true);
    try {
      const [visible,admin,frozen]=await Promise.all([api<StudyTask[]>('/study-tasks'),
        researcher ? api<TaskCandidate[]>('/task-candidates?full=true') : Promise.resolve(null),api<StudyTask[]>('/woz-tasks')]);
      setPublicTasks(visible);setWozTasks(frozen);if(admin)setTaskCandidates(admin);
    } finally {setTasksLoading(false);}
  }
  async function importTaskCandidate(candidate:unknown) {
    setBusy('과제를 등록하는 중');
    try {await api('/task-candidates/register',{candidate});await refreshTaskLibrary();}
    finally {setBusy('');}
  }
  async function prepareStudyTask(id:string,preview=false) {
    if(prototypeWorkspace){await chooseWozTask(id);setEntryOpen(true);setSettings(false);return;}
    await perform('입력 테이블을 불러오는 중',async()=>{
      const task=await api<PreparedTask>(`/${preview ? 'task-candidates' : 'study-tasks'}/${id}/input`);
      setPreparedTask({...task,researcherPreview:preview});setStudyInputCsv(task.input_csv);
      setStudyInputTable(task.input);setStudyUploadName('');setEntryOpen(true);setSettings(false);setSelection(null);
    });
  }
  async function uploadStudyInput(file:File) {
    await perform('입력 파일을 읽는 중',async()=>{
      if(file.size>1_000_000)throw new Error('Input 파일은 1 MB 이하이어야 합니다.');
      const bytes=await file.arrayBuffer();let text:string;
      try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{text=new TextDecoder('euc-kr').decode(bytes);}
      const table=await api<Table>('/preview',{text});setStudyInputCsv(text);setStudyInputTable(table);setStudyUploadName(file.name);
    });
  }
  function downloadStudyInput() {
    if(!preparedTask)return;
    const url=URL.createObjectURL(new Blob(['\ufeff'+preparedTask.input_csv],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=`${preparedTask.id}-input.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function startStudyTask() {
    if(!preparedTask)return;
    await perform('변환 코드를 준비하고 있어요',async()=>{
      setPreparing('executing');const started=performance.now();
      try {
        const path=preparedTask.researcherPreview ? 'task-candidates' : 'study-tasks';
        const result=await api<Session>(`/${path}/${preparedTask.id}/start`,{condition:cond,input_csv:studyInputCsv});
        setPreparing('presenting');
        const remaining=1200-(performance.now()-started);
        if(remaining>0)await new Promise(resolve=>setTimeout(resolve,remaining));
        accept(result);setSelection(null);setActiveOps({});
      } finally {setPreparing(null);}
    });
  }
  async function log(event: string, data = {}) { if (!session) return; try { await api(`/sessions/${session.id}/events`, { event, data, execution_version: session.run?.id, condition: session.condition }); } catch { setError('행동 로그 저장 실패. 네트워크 연결을 확인한 후 다시 시도하세요.'); } }
  useEffect(() => { api<NonNullable<typeof health>>('/health').then(h=>{setHealth(h);const key=h.pilot_account&&h.participant_id?`trace-session:${h.participant_id}`:prototypeWorkspace?'trace-woz-session':'trace-session';if(h.pilot_account){void api<AssignmentState>('/pilot-assignment').then(a=>{if(a.session_id)void api<Session>(`/sessions/${a.session_id}`).then(accept);else setEntryOpen(true);}).catch(e=>setError((e as Error).message));return;}const sid=new URLSearchParams(location.search).get('session')||localStorage.getItem(key);if(sid)api<Session>(`/sessions/${sid}`).then(accept).catch(()=>{localStorage.removeItem(key);const url=new URL(location.href);url.searchParams.delete('session');history.replaceState(null,'',url);});}).catch(() => setError('서버에 연결할 수 없습니다. FastAPI 서버를 실행해주세요.')); }, []);
  useEffect(() => { if (run && session && !entryVisible && !showEditor && !settings && run.explanation_status==='ready') void log('review_started', {presentation_version:'two-condition-v2', revision_interface:isEx?'panel-v1':'selection-action-v3', condition_variant:session.condition_variant, removed_rows_visible:!isEx, removed_rows_accessible:!isEx, removed_rows_presentation:isEx ? 'none' : 'before-table', workspace:isEx ? 'code-and-result' : 'before-and-after'}); }, [run?.id, session?.condition, run?.explanation_status, entryVisible, showEditor, settings]);

  const selectedReview = run?.stages.find(s => s.id === selection?.step);
  const selectedOperation = run?.operations?.find(s => s.id === selection?.operation_id);
  const detailOperation = selectedOperation;
  const selectedInput=selection?.table_role==='input'&&selectedReview?workflowInputs(selectedReview).find(item=>item.ref===selection.input_ref):undefined;
  const selectedInputOwner=selectedInput?workflowGraph.nodes.find(node=>node.id===ownerOf(workflowGraph,selectedInput.ref))?.stage:undefined;
  const selectedInputSnapshot=selectedInput?(run?.operations?.find(op=>op.id===selectedInput.ref)||selectedInputOwner):undefined;
  const selectedStage = selectedInput&&selectedReview ? {...(selectedInputSnapshot||{...selectedReview,params:{},column_explanations:{}}),id:selectedReview.id,table:selectedInput.table,lineage:selectedInputSnapshot?.lineage||{},row_sources:selectedInputSnapshot?.row_sources||{},trace_level:selectedInputSnapshot?.trace_level||'common'} : detailOperation ? { ...detailOperation, id: selectedReview?.id || detailOperation.id, label: selectedOperation ? detailOperation.label : selectedReview?.label || detailOperation.label } : selectedReview;
  const ctx = selection && selectedStage?.contexts?.[selection.row]?.[selection.column];
  const refs: Ref[] = selection ? selection.removed ? selectedStage?.removed_lineage?.[selection.row]?.[selection.column] || [] : selectedStage?.lineage[selection.row]?.[selection.column] || [] : [];
  const keyRefs = ctx?.key_sources || (selection ? selectedStage?.params.decision_sources?.[selection.row] : []) || [];
  const renderOtherOutputs=(stage:Stage)=>referencedOutputs(stage,run?.stages||[]).map((op,index)=><section className="workflow-export-card" key={op.id}><div><strong>후속 단계 참조 · 연산 {(stage.operations?.indexOf(op)??index)+1} 출력</strong><span>{op.table.stats.rows}행 × {op.table.stats.columns}열</span></div><DataTable data={op.table} stage={op} plain={isEx} integrated={!isEx} refs={isEx?[]:refs} keyRefs={isEx?[]:keyRefs}/></section>);
  const selectStep = (id: string, navigate = false) => { setFocus(id); if (selection?.step !== id) setSelection(null); if (id !== focus) { setComment(null);setCommentEditorOpen(false); } void log('step_selected', { step_id: id, navigation:navigate ? 'explicit-workflow' : 'none' }); };
  function navigateWorkflow(id: string) {

    setViewStep(id);
    selectStep(id,true);
  }
  function openComment(stage: Stage, target: ReviewTarget, anchor: HTMLElement, final = true,additive=false) {
    if (isEx || busy || !run || !session) return;
    const owner = run.stages.find(s => s.id === stage.id)!;
    const data = target.removed ? stage.removed : stage.table;
    if (!data) return;
    if(additive){
      const combined=combineSelection(pickedRef.current,target,data);
      if(!combined){pickedRef.current=null;setPickedTarget(null);setComment(null);setSelection(null);return null;}
      target=combined;
    }
    pickedRef.current=target;setPickedTarget(target);
    setFocus(stage.id);setCommentEditorOpen(false);setDragSelecting(!final);
    if (target.kind !== 'cell') setSelection(null);

    const row = data.rows.find(r => r.id === target.row_id);
    const multi = ['rows','columns','cells'].includes(target.kind);
    const chosenRows = target.row_ids ? data.rows.filter(r=>target.row_ids!.includes(r.id)) : data.rows;
    const chosenColumns = target.columns || data.columns;
    const kindLabel = target.kind==='cells'&&target.cells?target.cells.length+'개 셀':target.kind === 'cell' ? `셀 ${target.row_id} / ${target.column}` :
      target.kind === 'row' ? `행 ${target.row_id}` : target.kind === 'column' ? `열 ${target.column}` : target.kind === 'rows' ? `${chosenRows.length}개 행` : target.kind === 'columns' ? `${chosenColumns.length}개 열` : target.kind === 'cells' ? `${chosenRows.length}행 × ${chosenColumns.length}열 선택` : 'Step 전체';
    const preview = target.kind==='cells'&&target.cells?target.cells.length+'개 셀 선택\n'+target.cells.slice(0,6).map(point=>point.row_id+' · '+point.column+': '+fmt(data.rows.find(row=>row.id===point.row_id)?.values[point.column])).join('\n'):multi ? `${chosenRows.length}행 × ${chosenColumns.length}열 · ${chosenColumns.join(' · ')}\n${chosenRows.slice(0,3).map(r=>chosenColumns.slice(0,5).map(c=>fmt(r.values[c])).join(' · ')).join('\n')}${chosenRows.length>3 ? '\n…' : ''}` : target.kind === 'cell' ? `${target.column}: ${fmt(row?.values[target.column!])}` :
      target.kind === 'row' ? data.columns.map(c => `${c}: ${fmt(row?.values[c])}`).join(' · ') :
      target.kind === 'column' ? `${data.stats.rows}행 · ${data.rows.slice(0, 6).map(r => fmt(r.values[target.column!])).join(' · ')}${data.rows.length > 6 ? ' …' : ''}` :
      `${stage.input ? `입력 ${stage.input.stats.rows}행 × ${stage.input.stats.columns}열 → ` : ''}출력 ${data.stats.rows}행 × ${data.stats.columns}열`;
    setComment({ target, anchor, base_run_id: run.id, session_id: session.id, version: run.code_version,
      title: `${owner.kind === 'input' ? '입력' : `STEP ${String(owner.order).padStart(2, '0')} · ${stepTitle(owner)}`} / ${kindLabel}${target.removed ? ' · 제외된 입력' : ''}`,
      preview, scope: owner.kind === 'input' ? 'pipeline' : scope, error: '' });
    if (final) void log('review_target_selected', { target, interaction: 'selection-action-v3' });
    if (final && target.kind === 'row') void log('row_selected', { step_id: stage.id, row_id: target.row_id, removed: !!target.removed });
    if (final && target.kind === 'column') void log('column_selected', { step_id: stage.id, column: target.column, removed: !!target.removed });
    return target;
  }
  const selectCell = (stage:Stage,row:string,column:string,anchor:HTMLElement,removed=false,table_role:'input'|'output'='output',input_ref?:string,additive=false) => {
    if(isEx)return;
    const target=openComment(stage,{kind:'cell',step_id:stage.id,operation_id:stage.view_operation_id,row_id:row,column,removed,table_role,...(input_ref?{input_ref}:{})},anchor,true,additive);
    if(!target)return;
    const points=selectedCells(target,stage.table);
    if(points.length!==1)setSelection(null);else setSelection({step:stage.id,operation_id:stage.view_operation_id,row:points[0].row_id,column:points[0].column,removed,table_role,...(input_ref?{input_ref}:{})});
    void log('cell_selected',{step_id:stage.id,row_id:row,column,table_role,input_ref,selects:'cell'});
    void log('lineage_viewed',{step_id:stage.id,row_id:row,column,table_role,input_ref});
  };
  async function submitComment(){
    if(!comment||!session||!run||busy)return;
    const submitted=comment,text=(commentDrafts[draftKey(comment)]||'').trim();
    if(!text)return;
    if(submitted.base_run_id!==run.id){setComment({...submitted,error:'실행 버전이 변경되었습니다. 표를 다시 선택하세요.'});return;}
    setBusy('수정 코드 생성 · 재실행 중');setError('');setComment({...submitted,error:''});
    try{
      const next=await api<Session>(`/sessions/${session.id}/generate`,{request:text,scope:submitted.scope,base_run_id:submitted.base_run_id,
        context:{step_id:submitted.target.step_id,review_target:submitted.target,interaction:'selection-action-v3'}});
      accept(next);
      if(next.status==='ready'&&next.run){
        const anchor=document.getElementById('review-step-title-'+submitted.target.step_id)||submitted.anchor;
        setComment({...submitted,anchor,receipt:{run_id:next.run.id,version:next.run.code_version}});
        setCommentDrafts(drafts=>({...drafts,[draftKey(submitted)]:''}));
      }else setComment({...submitted,error:next.error?.message||'수정 요청 실패 · 마지막 성공 결과를 유지합니다.'});
    }catch(error){setComment({...submitted,error:(error as Error).message});}finally{setBusy('');}
  }
  async function previewText(text: string, dest: 'input' | 'target') { await perform('표 확인 중', async () => { const t = await api<Table>('/preview', { text }); (dest === 'input' ? setInputPreview : setTargetPreview)(t); }); }
  async function upload(file: File, dest: 'input' | 'target') {
    await perform('파일 읽는 중', async () => {
      if (file.size > 1_000_000) throw new Error('파일은 1 MB 이하이어야 합니다.');
      const buf = await file.arrayBuffer(); let text;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(buf); } catch { text = new TextDecoder('euc-kr').decode(buf); }
      const t = await api<Table>('/preview', { text });
      if (dest === 'input') { setInput(text); setInputPreview(t); } else { setTarget(text); setTargetPreview(t); }
    });
  }
  async function uploadExtra(files: FileList | null) {
    if (!files) return;
    await perform('추가 입력 표 읽는 중', async () => {
      const next = {...extraSources};
      for (const f of Array.from(files)) {
        if (f.size > 1_000_000) throw new Error('추가 입력도 파일당 1 MB 이하이어야 합니다.');
        const name = f.name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9_]/g, '_').replace(/^[0-9_]+/, '') || `source${Object.keys(next).length+1}`;
        if (name === 'input' || next[name]) throw new Error('추가 표 이름이 중복됩니다. 파일 이름을 변경해주세요.');
        if (Object.keys(next).length >= 4) throw new Error('추가 입력 표는 최대 4개입니다.');
        const buf = await f.arrayBuffer(); let text;
        try {text = new TextDecoder('utf-8',{fatal:true}).decode(buf);} catch {text = new TextDecoder('euc-kr').decode(buf);}
        next[name] = {text,table:await api<Table>('/preview',{text})};
      }
      setExtraSources(next);
    });
  }
  async function generate() { await perform('코드 생성 · 실제 실행 중', async () => {
    const s = await api<Session>('/sessions', { input_csv: input, target_csv: target, requirements, task_id: taskId, condition, sources: Object.fromEntries(Object.entries(extraSources).map(([k,v]) => [k,v.text])) });
    accept(s); setSelection(null);
    accept(await api<Session>(`/sessions/${s.id}/generate`, {}));
  }); }
  async function chooseWozTask(id:string){
    setWozTaskId('');setInput('');setTarget('');setInputPreview(null);setTargetPreview(null);setExtraSources({});
    if(!id)return;
    await perform('과제 표를 불러오는 중',async()=>{
      const task=await api<PreparedTask>(`/woz-tasks/${id}/input`);
      setWozTaskId(id);setInput(task.input_csv);setTarget(task.target_csv);setInputPreview(task.input);setTargetPreview(task.target);
      setRequirements('');setExtraSources(Object.fromEntries(Object.entries(task.sources).map(([name,table])=>[name,{text:'',table}])));
    });
  }
  async function startWoz(){await perform('변환 파이프라인을 준비하고 있어요',async()=>{
    if(!wozTaskId||!input.trim()||!target.trim())throw new Error('과제와 전체 Input·Target을 확인하세요.');
    setPreparing('executing');const started=performance.now();
    try{
      const result=await api<Session>(`/woz-tasks/${wozTaskId}/start`,{input_csv:input,target_csv:target,condition:cond});
      setPreparing('presenting');const remaining=1200-(performance.now()-started);
      if(remaining>0)await new Promise(resolve=>setTimeout(resolve,remaining));
      accept(result);setSelection(null);setRequest('');setScope('step');
    }finally{setPreparing(null);}
  });}
  async function importCode() { await perform('기존 코드 실제 실행 중',async () => {
    const code=researchCode, steps=researchSteps.trim() ? JSON.parse(researchSteps) : undefined;
    const s=await api<Session>('/sessions',{input_csv:input,target_csv:target,requirements,condition,task_id:taskId,execution_engine:'python',sources:Object.fromEntries(Object.entries(extraSources).map(([k,v]) => [k,v.text]))});
    accept(await api<Session>(`/sessions/${s.id}/research-code`,{code,steps,execution_engine:'python',structure_with_llm:structureWithLLM})); setSelection(null);setSettings(false);
  }); }
  async function loadDemo(correct = false) { await perform('데모 실행 중', async () => { accept(await api<Session>('/demo', { correct, condition: cond })); setSelection(null); setSettings(false); }); }
  function editData() { if (session) { setInput(session.input_csv); setTarget(session.target_csv); setRequirements(session.requirements); setInputPreview(session.input); setTargetPreview(session.target); setExtraSources(Object.fromEntries(Object.entries(session.sources_csv || {}).map(([k,text]) => [k,{text,table:session.sources![k]}]))); } setDraft(true); }
  async function revise() { if (!session) return; await perform('수정 코드 생성 · 재실행 중', async () => {
    const s = await api<Session>(`/sessions/${session.id}/generate`, { request, scope, base_run_id: session.run?.id, context: { step_id: focus.startsWith('source:')?'input':focus, selection, ...(comment&&comment.base_run_id===session.run?.id&&comment.target.step_id===focus?{review_target:comment.target,interaction:'shared-step-panel-v2'}:{}) } }); accept(s); if (s.status === 'ready') setRequest('');
  }); }
  const mutation = (path: string) => perform('처리 중', async () => { if (session) accept(await api<Session>(`/sessions/${session.id}/${path}`, {})); });

  const revisionForm = run && session ? <form className="review-request" onSubmit={e=>{e.preventDefault();void revise();}}>
    <div className="review-request-context"><label>수정 범위 <select aria-label="수정 범위" value={scope} disabled={!!busy} onChange={e=>setScope(e.target.value as 'step'|'pipeline')}><option value="step">선택 Step</option><option value="pipeline">전체 파이프라인</option></select></label>{comment?.base_run_id===run.id&&comment.target.step_id===focus&&<span>{comment.target.kind==='step'?'Step 전체':comment.preview.slice(0,100)}<button type="button" className="text-btn" onClick={()=>{setComment(null);setSelection(null);}}>선택 해제</button></span>}</div>
    <div className="review-request-entry"><textarea aria-label="자연어 수정 요청" placeholder="수정할 내용을 입력하세요" value={request} disabled={!!busy} onChange={e=>setRequest(e.target.value)}/><button className="primary" type="submit" disabled={!!busy||!request.trim()||(scope==='step'&&!run.stages.some(st=>st.id===focus&&st.kind!=='input'))}>{busy?<LoaderCircle className="spin" size={16}/>:null} 수정 요청</button></div>
  </form>:null;
  const revisionActions=run&&session?<div className="review-actions"><button className="text-btn" disabled={!!busy||(!run.parent_run_id&&session.status!=='failed')} onClick={()=>mutation('undo')}><RotateCcw size={14}/> 이전 실행으로 되돌리기</button><span className="execution-status">{busy|| (session.status==='failed'?'현재 요청 실패 · 마지막 성공 결과 표시 중':`실행 ${run.execution_ms.toFixed(0)} ms · v${run.code_version}`)}</span><button className="confirm-button" disabled={!!busy||session.status!=='ready'||!!session.confirmed} onClick={()=>mutation('confirm')}><Check size={16}/>{session.confirmed?'최종 확정 완료':'이 결과로 최종 확정'}</button></div>:null;
  const reviewStep=displayedStage?.kind!=='input'?displayedStage:run?.stages.find(stage=>stage.kind!=='input');
  const groups=reviewStep?reviewGroups(reviewStep):{inputRows:{},outputCells:{},groups:[]};

  return <><header className="app-header"><a className="brand" href="/" aria-label="Trace 홈"><span className="brand-mark"><GitBranch size={22}/></span>trace<span className="brand-dot">.</span></a><span className="header-divider"/><span className="lab-label">TABLE TRANSFORMATION LAB</span><div className="header-right"><span className="local-status">{health?.participant_id&&<b className="pilot-user-badge">{health.participant_id}</b>}<i/> {health?.team_mode ? '팀 파일럿 공간' : '로컬 연구 공간'}</span><span className="api-status header-api-status">{health?.api_configured ? <><i className="online"/> API 설정됨</> : <><i/> API 미연결</>}</span><div className="header-actions">{!health?.pilot_account&&<a className="secondary" href={prototypeWorkspace?'/?workspace=tasks':'/'}>{prototypeWorkspace?'과제 자료':'Input·Target 시작'}</a>}<button className="secondary" disabled={!!busy} onClick={()=>{setPreparedTask(null);setEntryOpen(true);setError('');}}><Layers3 size={15}/> {prototypeWorkspace?'새 Input·Target':health?.pilot_account?'배정 과제':'과제 선택'}</button>{!health?.pilot_account&&!prototypeWorkspace&&<button className="secondary" disabled={!!busy} onClick={() => loadDemo()}><FlaskConical size={15}/> 데모 열기</button>}{researcher && session && <a className="secondary" href={`/api/sessions/${session.id}/export`} download><Download size={15}/> 세션 내보내기</a>}</div>{canResearch && <button className="secondary developer-entry" aria-label="개발자 옵션" onClick={openDeveloper}><Settings2 size={16}/> 개발자 옵션</button>}<button className="icon-button" aria-label="지원 범위" onClick={() => { setSettings(true); }}><CircleHelp size={18}/></button></div></header>
    <main className={reviewScale===.67&&!entryVisible&&!showEditor&&run?'laptop-review-67':undefined}>
      {error && <div className="alert error" role="alert">{error}<button className="icon-button" onClick={() => setError('')} aria-label="알림 닫기"><X size={15}/></button></div>}
      {entryVisible&&prototypeWorkspace&&health&&!health.pilot_account&&<WozEntry tasks={wozTasks} taskId={wozTaskId} loading={wozLoading} researcher={researcher} busy={!!busy} condition={cond} onCondition={setCondition} onChoose={id=>void chooseWozTask(id)} onStart={()=>void startWoz()} onReturn={session?()=>setEntryOpen(false):undefined}>
        <UploadPanel title="입력 테이블" english="Input · 전체 표" text={input} setText={text=>{setInput(text);setInputPreview(null);}} preview={inputPreview} onPreview={()=>previewText(input,'input')} onFile={file=>upload(file,'input')}/>
        <div className="input-arrow"><ArrowRight size={18}/></div>
        <UploadPanel title="목표 테이블" english="Target · 현재 Input의 정확한 전체 출력" text={target} setText={text=>{setTarget(text);setTargetPreview(null);}} preview={targetPreview} onPreview={()=>previewText(target,'target')} onFile={file=>upload(file,'target')}/>
        {Object.entries(extraSources).map(([name,item])=><section key={name}><h3>{name} · 추가 입력</h3><DataTable data={item.table} plain/></section>)}
      </WozEntry>}
      {entryVisible&&prototypeWorkspace&&preparing&&<div className="study-preparing" role="status" aria-live="polite"><div><LoaderCircle className="spin" size={30}/><h3>{preparing==='presenting'?'검수 화면을 준비하고 있어요':'변환 파이프라인을 준비하고 있어요'}</h3><div className="study-progress"><span/></div></div></div>}
      {entryVisible && health?.pilot_account && <AssignedTaskEntry api={api} onRun={accept} onBusy={setBusy} renderTable={t=><DataTable data={t}/>}/>}
      {entryVisible && health && !health.pilot_account && !prototypeWorkspace && <StudyTaskEntry tasks={publicTasks} selected={preparedTask && {...preparedTask,input:studyInputTable || preparedTask.input}} busy={!!busy} loading={tasksLoading} preparing={preparing} uploaded={studyUploadName} researcher={canResearch} pilot={health?.pilot_account} condition={cond} onCondition={setCondition}
        onChoose={id=>void prepareStudyTask(id)} onUpload={f=>void uploadStudyInput(f)} onDownload={downloadStudyInput} onStart={()=>void startStudyTask()}
        onBack={()=>setPreparedTask(null)} onReturn={session ? ()=>setEntryOpen(false) : undefined} onDeveloper={openDeveloper} onCustom={()=>location.assign('/')}>
        {preparedTask && <><div className="study-input-target-grid"><section><h4>입력 테이블 · Input</h4><DataTable data={studyInputTable || preparedTask.input}/></section><section><h4>목표 테이블 · Target</h4><DataTable data={preparedTask.target}/></section></div>{Object.entries(preparedTask.sources).map(([name,t])=><section className="study-source" key={name}><h4>{name} · 추가 입력</h4><DataTable data={t}/></section>)}</>}
      </StudyTaskEntry>}
      {!entryVisible && <>
      {session?.error && !showEditor && <div className="alert error" role="alert"><div><strong>{session.error.phase === 'generation' ? '코드 생성 실패' : '코드 실행 실패'}</strong><p>{session.error.message}</p>{run && <small>아래는 마지막 성공 결과 · v{run.code_version}입니다. 실패한 코드는 적용되지 않았습니다.</small>}</div></div>}
      {showEditor&&<AutoHeight><section className="data-section"><div className="section-label"><span className="section-number">01</span><h2>입력과 목표</h2>{session?.task_display && <span className="study-task-number" title={session.task_display.title}>{taskNumber({id:session.task_id,review_number:session.task_display.review_number})}</span>}<span className="muted">DATA & INTENT</span>{isPrototype&&<button className="text-btn push" onClick={()=>setExpandedData(!expandedData)}>{expandedData?'표 접기':'전체 표 보기'}<ChevronDown size={13}/></button>}{session && !showEditor && !isPrototype && (researcher || !session.study_task) && <button className="text-btn push" disabled={!!busy} onClick={editData}>데이터 변경 <ArrowUpRight size={13}/></button>}{draft && <button className="text-btn push" onClick={() => setDraft(false)}>변경 취소 <X size={13}/></button>}</div>
        {showEditor ? <><div className="input-grid"><UploadPanel title="입력 테이블" english="Input" text={input} setText={s => { setInput(s); setInputPreview(null); }} preview={inputPreview} onPreview={() => previewText(input, 'input')} onFile={f => upload(f, 'input')}/><div className="input-arrow"><ArrowRight size={18}/></div><UploadPanel title="목표 테이블" english="Target" text={target} setText={s => { setTarget(s); setTargetPreview(null); }} preview={targetPreview} onPreview={() => previewText(target, 'target')} onFile={f => upload(f, 'target')}/></div><details className="additional-sources"><summary>추가 입력 테이블 · 병합·조인 <span>{Object.keys(extraSources).length}개</span></summary><label className="secondary file-label"><Upload size={14}/> CSV 추가<input aria-label="추가 입력 CSV" type="file" multiple accept=".csv,.tsv,.txt" onChange={e => {void uploadExtra(e.target.files);e.target.value='';}}/></label>{Object.entries(extraSources).map(([name,v]) => <section key={name}><div className="panel-heading"><span>{name}</span><button className="text-btn push" onClick={() => {const next={...extraSources};delete next[name];setExtraSources(next);}}>제거</button></div><DataTable data={v.table} compact limit={3}/></section>)}</details><div className="requirements-entry"><div><label htmlFor="requirements">변환 요구사항 <span>선택</span></label><input id="requirements" value={requirements} onChange={e => setRequirements(e.target.value)} placeholder="예: 완료 주문 중 수량이 2 이상인 주문의 지역별 매출 합계"/></div><button className="primary" disabled={!!busy || !input.trim() || !target.trim()} onClick={generate}>{busy ? <LoaderCircle className="spin" size={16}/> : <Sparkles size={16}/>} 변환 코드 생성</button></div><div className="data-note"><span>Target = 현재 Input에 대한 기대 출력</span><span>실제 생성에는 서버 API 키가 필요합니다.</span></div></> : session && <><div className={"input-grid previews " + (!session.target ? "input-only" : "")}><section className="preview-panel"><div className="panel-heading"><Table2 size={16}/><h3>입력 테이블 <span>Input</span></h3><span className="table-count push">{session.input.stats.rows}행 × {session.input.stats.columns}열</span></div><DataTable data={session.input} compact limit={expandedData ? undefined : 3}/></section>{session.target && <><div className="input-arrow"><ArrowRight size={18}/></div><section className="preview-panel"><div className="panel-heading"><span className="target-dot"/><h3>목표 테이블 <span>Target</span></h3><span className="table-count push">{session.target.stats.rows}행 × {session.target.stats.columns}열</span></div><DataTable data={session.target} compact limit={expandedData ? undefined : 3}/></section></>}</div>{Object.entries(session.sources || {}).map(([name,t]) => <details className="additional-sources" key={name}><summary>{name} · 추가 입력 {t.stats.rows}행 × {t.stats.columns}열</summary><DataTable data={t} compact limit={expandedData ? undefined : 3}/></details>)}{!isPrototype&&<div className="task-bar"><span className="task-tag">요구사항</span><span>{session.requirements || '추가 요구사항 없음'}</span><button className="text-btn push" onClick={() => setExpandedData(!expandedData)}>{expandedData ? '접기' : '전체 표'} <ChevronDown size={13}/></button></div>}</>}
      </section></AutoHeight>}
      {showEditor && researcher && <details className="existing-code"><summary>기존 생성 코드로 검수 시작 · 연구자</summary><label>Python 코드<textarea aria-label="기존 Python 코드" className="research-code" value={researchCode} onChange={e => setResearchCode(e.target.value)} placeholder="input_df와 tables를 사용하고 마지막 출력은 result DataFrame으로 두세요."/></label><label>Step 메타데이터 JSON · 선택<textarea aria-label="Step 메타데이터 JSON" value={researchSteps} onChange={e => setResearchSteps(e.target.value)} placeholder={'[{"label":"정리","statement_indices":[0,1],"output_variable":"s1"}, ...]'}/></label><label><input type="checkbox" checked={structureWithLLM} onChange={e => setStructureWithLLM(e.target.checked)}/> LLM으로 Step 구성 · 코드 원문 보존</label><p>미선택 시 구문 단위로 관찰합니다. 이 경계는 의미적 Step 품질을 검증한 것이 아닙니다.</p><button className="primary" disabled={!!busy || !researchCode.trim() || !input.trim() || !target.trim()} onClick={importCode}>기존 코드 실행</button></details>}
      {researcher && session?.error?.partial_stages?.length ? <section className="failed-prefix"><h3>실패한 시도 · 관찰된 앞부분</h3><p>{session.error.failure?.step_id} · {session.error.failure?.message}</p><div className="workflow">{session.error.partial_stages.map(st => <article className="stage-card" key={st.id}><h3>{st.label}</h3><p>{st.summary}</p><DataTable data={st.table}/>{cond === 'ex' && <PythonCode code={st.code}/>}</article>)}</div></section> : null}
      {!showEditor && session && !run && !busy && <div className="blank-state"><Braces size={30}/><h3>아직 실행된 변환이 없습니다.</h3><button className="primary" onClick={() => mutation('generate')}><Sparkles size={15}/> 다시 생성</button></div>}
      {!showEditor&&session&&run&&reviewStep&&<><ReviewWorkspace condition={cond} steps={run.stages.filter(stage=>stage.kind!=='input')} selected={reviewStep} busy={!!busy} explanation={exText(reviewStep)} title={exTitle} onSelect={navigateWorkflow} version={run.code_version} canSwitch={!health?.pilot_account} onReviewStep={anchor=>openComment(reviewStep,{kind:'step',step_id:reviewStep.id},anchor)}
        onCondition={id=>void perform('동일 실행의 표현 전환 중',async()=>{setSelection(null);setComment(null);accept(await api<Session>(`/sessions/${session.id}/condition`,{condition:id}));})}
        input={<><DataTable data={session.input} plain/>{Object.entries(session.sources||{}).map(([name,t])=><section key={name}><h3>{name}</h3><DataTable data={t} plain/></section>)}</>}
        target={session.target?<DataTable data={session.target} plain/>:<p>Target이 없습니다.</p>}
        before={<>{workflowInputs(reviewStep).map((item,index)=>{const owner=ownerOf(workflowGraph,item.ref),known=run.operations?.find(op=>op.id===item.ref)||workflowGraph.nodes.find(node=>node.id===owner)?.stage;const snapshot=known?{...known,table:item.table}:{...run.stages[0],table:item.table,lineage:{},row_sources:{},trace_level:'common'};return <section className="review-input-table" key={item.ref+index}><small>{item.variable||'입력'} · {item.table.stats.rows}행</small><DataTable data={item.table} stage={{...snapshot,id:reviewStep.id,view_operation_id:undefined}} tableRole="input" inputRef={item.ref} selection={selection} reviewTarget={pickedTarget} selectionDisabled={!!busy}
            onSelect={(row,column,anchor,additive)=>selectCell({...reviewStep,table:item.table},row,column,anchor,false,'input',item.ref,additive)}
            onSelectRange={(target,anchor,final)=>openComment({...reviewStep,table:item.table},target,anchor,final)}
            onSelectRow={(row,anchor,additive)=>openComment({...reviewStep,table:item.table},{kind:'row',step_id:reviewStep.id,row_id:row,table_role:'input',input_ref:item.ref},anchor,true,additive)}
            onSelectColumn={(column,anchor,additive)=>openComment({...reviewStep,table:item.table},{kind:'column',step_id:reviewStep.id,column,table_role:'input',input_ref:item.ref},anchor,true,additive)}
            integrated inputDelta={workflowInputs(reviewStep).length===1?tableChanges(reviewStep):null} groupRows={groups.inputRows} refs={refs} keyRefs={keyRefs}/></section>;})}{!workflowInputs(reviewStep).length&&<p>이 Step의 입력 표 대응은 확인되지 않았습니다.</p>}</>}
        after={<><DataTable data={reviewStep.table} stage={reviewStep} plain={isEx} integrated={!isEx} delta={isEx?null:tableChanges(reviewStep)} groupCells={isEx?undefined:groups.outputCells} selection={isEx?null:selection} refs={isEx?[]:refs} keyRefs={isEx?[]:keyRefs} reviewTarget={pickedTarget} selectionDisabled={!!busy}
          onSelect={isEx?undefined:(row,column,anchor,additive)=>selectCell(reviewStep,row,column,anchor,false,'output',undefined,additive)}
          onSelectRange={isEx?undefined:(target,anchor,final)=>openComment(reviewStep,target,anchor,final)}
          onSelectRow={isEx?undefined:(row,anchor,additive)=>openComment(reviewStep,{kind:'row',step_id:reviewStep.id,row_id:row},anchor,true,additive)}
          onSelectColumn={isEx?undefined:(column,anchor,additive)=>openComment(reviewStep,{kind:'column',step_id:reviewStep.id,column},anchor,true,additive)}/>
          {renderOtherOutputs(reviewStep)}</>}
        changeLegend={groups.groups.length?<div className="review-group-legend"><span>같은 색: 집계 그룹·결과값</span>{groups.groups.map(group=><span key={group.index} style={{background:groupColor(group.index),borderColor:groupBorder(group.index)}}>G{group.index+1} · {group.label}</span>)}</div>:null} footer={isEx?revisionForm:null}/>
        {!explanationsReady(run)&&<div className="explanation-status" role="status"><span>{run.explanation_error||'자연어 설명을 준비하지 못했습니다.'}</span><button className="secondary" disabled={!!busy} onClick={()=>void perform('자연어 설명 생성 중',async()=>accept(await api<Session>(`/sessions/${session.id}/explanations`,{run_id:run.id})))}>설명 다시 불러오기</button></div>}
        {revisionActions}{session.review_baseline&&<InitialStepJudgment key={`${session.id}:${run.id}:${session.condition}`} session={session} api={api} busy={!!busy}/>}<details className="assumptions"><summary>생성 시 사용한 가정 · {run.assumptions.length}</summary><ul>{run.assumptions.map((assumption,index)=><li key={index}>{assumption}</li>)}</ul></details>
      </>}
      {showEditor && !session && <section className="welcome-panel"><div className="welcome-symbol"><Layers3 size={27}/></div><h3>작은 변화도, 명확하게.</h3><p>표를 등록하거나 준비된 주문 데이터로 검수 과정을 시작하세요.</p><button className="text-btn" disabled={!!busy} onClick={() => loadDemo()}>데모로 시작하기 <ArrowRight size={14}/></button><div className="capability-tags"><span><Filter size={12}/> 필터·계산·집계</span><span><Columns3 size={12}/> 열·타입·결측 정리</span><span><GitBranch size={12}/> 병합·재구조화</span></div></section>}
      </>}
      {session&&!entryVisible&&!showEditor&&health?.pilot_account&&<PilotFeedback key={`${session.id}:${run?.id}:${session.condition}`} session={session} api={api} busy={!!busy} onNext={()=>{setEntryOpen(true);setPreparedTask(null);setSelection(null);}}/>}
      <footer className="page-footer"><span>trace. <span>실행 기록 기반 테이블 변환 검수</span></span><span>{health?.team_mode ? '팀 파일럿 · 데이터는 관리자 서버에 저장됩니다' : '연구용 프로토타입 · 데이터는 로컬에 저장됩니다'}</span></footer>
    </main>
    {comment&&!isEx&&!showEditor&&!entryVisible&&!settings&&(commentEditorOpen?<ReviewComment key={draftKey(comment)} anchor={comment.anchor} title={comment.title} preview={comment.preview} version={comment.version}
      value={commentDrafts[draftKey(comment)]||''} onChange={text=>setCommentDrafts(drafts=>({...drafts,[draftKey(comment)]:text}))}
      scope={comment.scope} onScope={value=>{setScope(value);setComment(current=>current?{...current,scope:value}:null);}} source={false} demo={run?.mode==='demo'} busy={!!busy} error={comment.error} receipt={comment.receipt}
      history={commentRuns.filter(item=>item.review_comment?.target.step_id===comment.target.step_id).slice(-5)} onClose={()=>setCommentEditorOpen(false)} onSubmit={()=>void submitComment()}/>
      :!dragSelecting&&!busy&&<SelectionAction anchor={comment.anchor} columnInfo={selection&&selectedStage&&(selectedStage.params.formulas?.[selection.column]||selectedStage.params.aggregations?.[selection.column]||selectedStage.column_explanations?.[selection.column]||tableChanges(selectedStage)?.addedColumns.includes(selection.column))?<ColumnOriginDetails stage={selectedStage} column={selection.column}/>:undefined} onEdit={()=>{setCommentEditorOpen(true);void log('review_comment_opened',{target:comment.target,interaction:'selection-action-v3'});}} onDismiss={()=>setComment(null)}/>)}
    {settings && <div className="drawer-backdrop" onClick={() => setSettings(false)}><aside className={"settings-drawer " + (researcher ? "developer-drawer" : "")} onClick={e => e.stopPropagation()}><div className="drawer-header"><h2>{researcher ? '개발자 옵션' : '지원 범위'}</h2><button className="icon-button" aria-label="설정 닫기" onClick={() => setSettings(false)}><X size={20}/></button></div>{researcher && <><div className="developer-tabs"><button className={developerTab==='tasks'?'active':''} onClick={()=>setDeveloperTab('tasks')}>과제 관리</button><button className={developerTab==='logs'?'active':''} onClick={()=>setDeveloperTab('logs')}>파일럿 로그</button></div>{developerTab==='logs'?<PilotRecords api={api} admin onDiscarded={ids=>{if(session&&ids.includes(session.id)){localStorage.removeItem('trace-session');if(session.participant_id)localStorage.removeItem(`trace-session:${session.participant_id}`);setSession(null);setEntryOpen(true);setPreparedTask(null);setComment(null);const url=new URL(location.href);url.searchParams.delete('session');history.replaceState(null,'',url);}}}/>:<TaskCatalog tasks={taskCandidates} busy={!!busy} onRefresh={()=>void perform('과제 목록 갱신 중',refreshTaskLibrary)} onImport={importTaskCandidate} onPrepare={id=>void prepareStudyTask(id,true)}
        onLoad={(id,reference)=>void perform('과제 코드 실행 중',async()=>{accept(await api<Session>(`/task-candidates/${id}/${reference ? 'load' : 'start'}`,{condition:cond,...(reference ? {variant:'reference'} : {})}));setSelection(null);setSettings(false);})}
        onPublish={(id,visible)=>void perform('과제 공개 설정 중',async()=>{await api(`/task-candidates/${id}/publication`,{visible});await refreshTaskLibrary();})}/> }
      <div className="developer-current"><span>현재 조건 <b>{conditionLabel(cond)}</b></span><span>현재 실행 <b>{run ? `v${run.code_version} · ${run.mode==='demo' ? '데모' : run.mode==='research' ? '저장/등록 코드' : 'API 생성·수정'}` : '없음'}</b></span></div>
      <details className="developer-advanced"><summary>조건 변경 · 코드 등록 · 재현 · 연구자 진단</summary>{run?.comparison && session && session.target && <details className="research-diagnostics"><summary>연구자 전용 평가 진단</summary><div className="settings-group"><span className={run.comparison.matches ? 'match-state' : 'mismatch-state'}>{run.comparison.matches ? '현재 Target과 일치' : `현재 Target과 차이 · ${run.comparison.differences.length}셀`}</span><div className="mini-title">실제 결과</div><DataTable data={observedOutput!} compact/><div className="mini-title">기대 출력</div><DataTable data={session.target} compact/>{!run.comparison.same_columns && <span>열 이름 또는 열 순서 차이</span>}<div className="difference-list">{run.comparison.differences.map((d,i) => <span key={i}>{d.row}행 · {d.column}: {fmt(d.actual)} → Target {fmt(d.expected)}</span>)}</div></div></details>}<div className="settings-group"><label>검수 조건</label><div className="condition-options">{(['ex','in-situ'] as const).map((c, i) => <button key={c} disabled={!!busy} className={cond === c ? 'active' : ''} onClick={() => perform('조건 적용 중', async () => { setCondition(c); setSelection(null); setActiveOps({}); if (session) accept(await api<Session>(`/sessions/${session.id}/condition`, { condition: c })); })}><b>{conditionLabel(c)}</b><span>{c==='ex'?'코드·설명·중간 결과':'설명·전후 표·실제 변화'}</span>{cond === c && <Check size={15}/>}</button>)}</div><p>조건 변경은 현재 코드와 실행 기록을 재사용합니다.</p></div><div className="settings-group"><label htmlFor="task-id">새 과제 식별자</label><input id="task-id" value={taskId} onChange={e => setTaskId(e.target.value)}/></div><div className="settings-group"><label>준비된 연구 코드</label><div className="button-pair"><button className="secondary" disabled={!!busy} onClick={() => perform('확장 예제 실행 중',async () => {accept(await api<Session>('/demo/wrangling',{condition:cond}));setSelection(null);setActiveOps({});setSettings(false);})}>확장 랭글링 예제</button><button className="secondary" disabled={!!busy} onClick={() => loadDemo(true)}>정상 코드</button><button className="secondary" disabled={!!busy} onClick={() => loadDemo(false)}>경계값 오류 코드</button></div></div><div className="settings-group"><label>세션 재현</label><input ref={fileRef} hidden type="file" accept=".json" onChange={e => { const f = e.target.files?.[0]; if (f) void perform('세션 읽는 중', async () => { const json = JSON.parse(await f.text()); if (!json.runs?.length) throw new Error('실행 기록이 있는 세션 파일이 필요합니다.'); setReplayFile(json); setReplayIndex(0); }); e.target.value = ''; }}/><button className="secondary" onClick={() => fileRef.current?.click()}><Upload size={14}/> 내보낸 JSON 선택</button>{replayFile && <><select aria-label="재현 실행 버전" value={replayIndex} onChange={e => setReplayIndex(Number(e.target.value))}>{(replayFile.runs as Run[]).map((r, i) => <option key={r.id} value={i}>v{r.code_version}{i === 0 ? ' · 초기 코드' : ''}</option>)}</select><button className="primary" disabled={!!busy} onClick={() => perform('저장 코드 재실행 중', async () => { accept(await api<Session>('/replay', { session: replayFile, condition: cond, run_index: replayIndex })); setSelection(null); setSettings(false); })}><Play size={14}/> 동일 코드로 새 세션</button></>}</div>{session && <div className="settings-group"><label htmlFor="research-code">연구자 코드 등록</label><textarea id="research-code" className="research-code" value={researchCode} onChange={e => setResearchCode(e.target.value)}/><button className="secondary" disabled={!!busy} onClick={() => perform('연구 코드 실행 중', async () => { accept(await api<Session>(`/sessions/${session.id}/research-code`, { code: researchCode,steps:researchSteps.trim() ? JSON.parse(researchSteps) : undefined, execution_engine:'python', structure_with_llm:structureWithLLM })); setSettings(false); })}><Play size={14}/> 등록 및 실행</button></div>}</details></>}
      <div className="settings-group"><label>실행기</label><p>Python/pandas 실제 실행 · 파일·네트워크·동적 코드 실행 차단 · 입력 표당 500행·32열 / 결과 2000행·64열</p><div className="scope-list"><span>✓ 필터·계산·그룹 집계: 조건·기여 행</span><span>✓ 열·타입·정렬·결측·중복·문자열·날짜: 셀 출처</span><span>✓ 병합·행 결합·긴 형식·목록 펼치기: 원본 셀 추적</span><span>◇ 상세 어댑터 밖 연산: 실행 및 전후 표 / 셀 계보 미확인</span><span>✓ 일반 Python: 함수·apply·반복·분기·직접 열 변경</span></div></div><div className="settings-group"><label>API 상태</label><p>{health?.api_configured ? `연결 설정됨 · ${health.model}` : 'OPENAI_API_KEY 미설정'}</p><p>API 키와 모델은 서버 환경변수에서 설정합니다. 데모는 사전 코드와 제한된 수정 규칙을 사용합니다.</p></div><div className="settings-group"><label>결측·비교 정책</label><p>빈 셀은 결측입니다. 결측 그룹을 유지하고 집계는 pandas 기본 규칙을 따릅니다. Target은 현재 입력의 기대 출력이며 행·열 순서와 수치 오차 1e−9를 기준으로 비교합니다.</p></div>{session && <div className="session-meta"><span>SESSION</span><code>{session.id}</code><span>EXECUTION</span><code>{run?.id || '—'}</code></div>}</aside></div>}
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
