import json
import hashlib
import os
import platform
import threading
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import pandas as pd

from .engine import compare, parse_table, table
from .runtime import CAPABILITIES
from .pipeline import prepare, patch, assemble, validate_scope
from .isolation import isolated_run
from .access import gate, origins, request_identity
from .pilot import Feedback, session_summary, csv_text
from .pilot_plan import progress as pilot_progress
from . import explanations
from . import candidates
from .review_context import resolve_review_target
from .review_presentation import present_run
from . import prototype
from . import judgments
from .conditions import normalize as normalize_condition, VARIANTS as CONDITION_VARIANTS
from .generator import (DEMO_INPUT, DEMO_REQUIREMENTS, DEMO_TARGET,
                        OpenAIGenerator, demo_code, revise_demo, DEFAULT_MODEL,
                        WRANGLING_INPUT, WRANGLING_TARGET, WRANGLING_SOURCES, WRANGLING_CODE, WRANGLING_STEPS)

ROOT = Path(__file__).resolve().parent.parent
# Minimal .env loader: never overwrite process environment or write credentials.
if (ROOT / '.env').exists():
    for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
STORE = Path(os.getenv('TRACE_DATA_DIR', str(ROOT / '.local' / 'sessions'))).resolve()
STORE.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='Trace table research', version='0.1.0')
generator = OpenAIGenerator()
locks = {}
locks_guard = threading.Lock()
def condition_variant(condition,study_mode=None):
    try:return CONDITION_VARIANTS[normalize_condition(condition)]
    except ValueError:return 'unknown'


def active_condition(value):
    try:return normalize_condition(value)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


def now():
    return datetime.now(timezone.utc).isoformat()


def path(sid):
    try:
        uuid.UUID(sid)
    except (ValueError, AttributeError):
        raise HTTPException(404, '세션을 찾을 수 없습니다.')
    return STORE / f'{sid}.json'


def lock(sid):
    with locks_guard:
        return locks.setdefault(sid, threading.RLock())


def read(sid):
    p = path(sid)
    if not p.exists():
        raise HTTPException(404, '세션을 찾을 수 없습니다.')
    s = json.loads(p.read_text(encoding='utf-8'))
    who=request_identity.get()
    if who and who['role']=='participant' and s.get('participant_id')!=who['participant_id']:
        raise HTTPException(404,'세션을 찾을 수 없습니다.')
    changed = False
    # Preserve historic events. New interactions use the active two conditions.
    old_condition=s.get('condition','in-situ')
    s['condition']=active_condition(old_condition)
    if old_condition!=s['condition']:
        s.setdefault('legacy_condition',old_condition)
        s.setdefault('legacy_condition_variant',s.get('condition_variant'))
    for r in s['runs']:
        if 'pipeline' not in r:
            parent = next((v for v in s['runs'] if v['id'] == r.get('parent_run_id')), None)
            r['pipeline'] = prepare(r['code'], previous=parent)
            for st, spec in zip(r['stages'][1:], r['pipeline']['steps']):
                st.update(id=spec['id'], revision=spec['revision'], trace_level='detailed', operations=[], depends_on=[], diff={})
            r['operations'] = []
            r['cumulative_requirements'] = ([s['requirements']] if s['requirements'] else []) + [v['revision_request'] for v in s['runs'] if v.get('revision_request') and v['code_version'] <= r['code_version']]
            changed = True
    s.setdefault('sources_csv', {})
    s.setdefault('sources', {})
    s['condition_variant'] = condition_variant(s['condition'],s.get('study_mode'))
    s['presentation_version']='two-condition-v2'
    if s.get('prototype'):s['prototype']={**s['prototype'],'condition_ids':list(CONDITION_VARIANTS)}
    if changed:
        s['schema_version'] = 2
        save(s)
    return s


def save(s):
    p = path(s['id'])
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(s, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(p)


def current(s):
    return s['runs'][s['cursor']] if s['cursor'] >= 0 else None


def event(s, name, data=None):
    r = current(s)
    s['events'].append({'id': str(uuid.uuid4()), 'timestamp': now(), 'event': name,
                        'participant_id':s.get('participant_id'),'actor_id':(request_identity.get() or {}).get('name','local'),
                        'review_number':s.get('task_display',{}).get('review_number'),
                        'assignment_id':s.get('assignment',{}).get('id'),'plan_version':s.get('assignment',{}).get('plan_version'),
                        'study_mode':s.get('study_mode','legacy-local'),'presentation_version':'two-condition-v2',
                        'session_id': s['id'], 'task_id': s['task_id'], 'condition': s['condition'],
                        'condition_variant': condition_variant(s['condition'],s.get('study_mode')),
                        'code_version': r['code_version'] if r else None,
                        'execution_version': r['id'] if r else None, 'data': data or {}})


def review_duration(s):
    r = current(s)
    for e in reversed(s['events']):
        if r and e['execution_version'] == r['id'] and e['condition'] == s['condition'] and e['event'] in ('review_started', 'review_resumed'):
            return max(0, round((datetime.now(timezone.utc) - datetime.fromisoformat(e['timestamp'])).total_seconds() * 1000))
    return None


def execute(s, code, assumptions, mode, request=None, groups=None, prepared=None):
    start = time.perf_counter()
    previous = current(s)
    engine=s.get('execution_engine','capability')
    plan = prepared or prepare(code, groups, previous, engine=engine)
    records = isolated_run(plan['code'], s['input_csv'], s.get('sources_csv', {}),engine=plan['engine'],plan=plan)
    stages, operations = assemble(records, plan, previous)
    version = len(s['runs']) + 1
    rid = str(uuid.uuid4())
    for stage in stages:
        stage.update(code_version=version, execution_version=rid)
    for op in operations:
        op.update(code_version=version, execution_version=rid)
    cumulative = list(previous.get('cumulative_requirements', [])) if previous else ([s['requirements']] if s['requirements'] else [])
    if request:
        cumulative.append(request)
    result = {'id': rid, 'code_version': version, 'created_at': now(), 'code': plan['code'], 'mode': mode,
              'pipeline': plan, 'operations': operations, 'cumulative_requirements': cumulative,
              'assumptions': assumptions, 'revision_request': request, 'stages': stages,
              'comparison': compare(stages[-1]['table'], s['target']),
              'execution_ms': round((time.perf_counter() - start) * 1000, 2),
              'parent_run_id': current(s)['id'] if current(s) else None,
              'runtime': {'python': platform.python_version(), 'pandas': pd.__version__, 'engine': 'native-python-v3' if plan['engine']=='python' else 'capability-pandas-v2', 'wall_limit_seconds': 20, 'process_memory_mb': 512 if os.name == 'nt' else None, 'credentials_in_worker': False},
              'generator_settings': {'model': os.getenv('OPENAI_MODEL', DEFAULT_MODEL), 'reasoning_effort': os.getenv('OPENAI_REASONING_EFFORT'), 'contract': 'semantic-steps-and-patches-v3'} if mode == 'api' else None,
              'generator_model': os.getenv('OPENAI_MODEL', DEFAULT_MODEL) if mode == 'api' else None}
    s['runs'].append(result)
    s['cursor'] = len(s['runs']) - 1
    s.update(status='ready', error=None, confirmed=None)
    return result


def view(s):
    runs=[present_run(run) for run in s['runs']]
    result={**s,'runs':runs,'condition_variant':condition_variant(s['condition'],s.get('study_mode')),
            'run':runs[s['cursor']] if s['cursor']>=0 else None}
    if s.get('study_task'):result['study_task']={**s['study_task'],'target_visibility':'participant'}
    return result


def participant_view(payload):
    """Remove evaluator verdicts and researcher diagnostics from browser responses.

    Display projection only; researcher URL/header is not an authentication boundary.
    The canonical stored session/export remains available for research evaluation.
    """
    if not isinstance(payload,dict) or not isinstance(payload.get('runs'),list) or 'input_csv' not in payload:return payload
    # Schema-aware projection: never filter actual table cells by their column names.
    result={k:v for k,v in payload.items() if k not in ('events','failed_attempts','task_provenance','judgment_evaluations')}
    def redact_run(run):
        return {k:v for k,v in run.items() if k!='comparison'} if run else run
    result['runs']=[redact_run(r) for r in payload['runs']]
    if 'run' in payload:result['run']=redact_run(payload['run'])
    if isinstance(payload.get('error'),dict):
        result['error']={'phase':payload['error'].get('phase'),
                         'message':'새 실행이 완료되지 않았습니다. 이전 실행 결과를 확인하거나 다시 요청해 주세요.'}
    return result


def partial_stages(exc,plan,attempt_id=None):
    records=getattr(exc,'records',[])
    if not plan or len(records)<2:return []
    completed={r.get('statement_index') for r in records[1:]}
    specs=[st for st in plan['steps'] if any(i in completed for i in st['statement_indices'])]
    try:
        stages=assemble(records,{**plan,'steps':specs})[0]
        for st in stages:
            for item in [st]+st.get('operations',[]):
                item.update(execution_version=attempt_id,result_status='partial')
        return stages
    except Exception:return []


class Tables(BaseModel):
    input_csv: str = Field(max_length=1_000_000)
    target_csv: str = Field(max_length=1_000_000)
    requirements: str = Field(default='', max_length=5000)
    task_id: str = Field(default='custom-task', max_length=100)
    condition: str = 'in-situ'
    sources: dict[str, str] = Field(default_factory=dict, max_length=4)
    execution_engine: str='python'


class Preview(BaseModel):
    text: str = Field(max_length=1_000_000)


@app.get('/api/health')
def health(request: Request):
    return {'ok': True, 'access_role':getattr(request.state,'access_role','local'), 'team_mode':bool(getattr(request.state,'access_config',None)),
            'participant_id':(request.state.access_identity or {}).get('participant_id'),
            'pilot_account':bool((request.state.access_identity or {}).get('pilot')),
            'api_configured': bool(os.getenv('OPENAI_API_KEY')), 'model': os.getenv('OPENAI_MODEL', DEFAULT_MODEL),
            'model_verification': 'default_id_officially_verified; configured_account_access_not_tested',
            'supported': CAPABILITIES, 'default_execution':'native-python',
            'supported_is':'optional detailed tracing adapters, not an execution whitelist',
            'max_rows': 500, 'max_result_rows': 2000, 'isolation': 'subprocess + code policy + IO audit + 20s timeout + Windows 512MB Job'}


@app.post('/api/preview')
def preview(body: Preview):
    try:
        return table(parse_table(body.text))
    except Exception as exc:
        raise HTTPException(422, str(exc))


@app.post('/api/sessions')
def create(body: Tables):
    if body.execution_engine not in ('python','capability'):raise HTTPException(422,'잘못된 실행기')
    body.condition=active_condition(body.condition)
    if body.condition not in CONDITION_VARIANTS:
        raise HTTPException(422, '지원하지 않는 조건입니다.')
    try:
        inp, target = table(parse_table(body.input_csv)), table(parse_table(body.target_csv))
        if any(not name.isidentifier() or name.startswith('_') or name == 'input' for name in body.sources):
            raise ValueError('추가 표 이름은 input 이외의 식별자여야 합니다.')
        if sum(len(t.encode()) for t in [body.input_csv, body.target_csv, *body.sources.values()]) > 3_000_000:
            raise ValueError('전체 입력·목표 합계는 3 MB 이하이어야 합니다.')
        source_tables = {}
        for name, csv in body.sources.items():
            df = parse_table(csv)
            df.index = [f'{name}:{r}' for r in df.index]
            source_tables[name] = table(df)
    except Exception as exc:
        raise HTTPException(422, str(exc))
    who=request_identity.get() or {}
    s = {'schema_version': 2, 'id': str(uuid.uuid4()), 'task_id': body.task_id, 'condition': body.condition,
         'participant_id':who.get('participant_id'),'creator_id':who.get('name','local'),
         'pilot_account':bool(who.get('pilot')),'feedbacks':[],
         'study_mode':os.getenv('TRACE_STUDY_MODE','local'),
         'condition_variant': condition_variant(body.condition),
         'created_at': now(), 'input_csv': body.input_csv, 'target_csv': body.target_csv,
         'input': inp, 'target': target, 'requirements': body.requirements, 'target_semantics': 'expected_output',
         'sources_csv': body.sources, 'sources': source_tables,
         'execution_engine':body.execution_engine,'runs': [], 'cursor': -1, 'events': [], 'status': 'registered', 'error': None, 'confirmed': None}
    event(s, 'input_registered', {'rows': inp['stats']['rows'], 'columns': inp['columns']})
    event(s, 'target_registered', {'rows': target['stats']['rows'], 'columns': target['columns'], 'semantics': 'expected_output'})
    for name, t in source_tables.items():
        event(s, 'input_registered', {'table_id': name, 'rows': t['stats']['rows'], 'columns': t['columns']})
    save(s)
    return view(s)


@app.get('/api/prototype/fixture')
def prototype_fixture():
    return {'input_csv':prototype.INPUT,'target_csv':prototype.TARGET,
            'input':table(parse_table(prototype.INPUT)),'target':table(parse_table(prototype.TARGET)),
            'purpose':'prototype-validation','selected_for_study':False}


@app.post('/api/prototype/sessions')
def create_prototype(body:prototype.PrototypeTables):
    result=create(Tables(input_csv=body.input_csv,target_csv=body.target_csv,sources=body.sources,
                        requirements='',condition=body.condition,execution_engine='python',task_id='prototype-user-tables'))
    with lock(result['id']):
        s=read(result['id']);s.update(study_mode=prototype.MODE,pilot_account=False,
            research_phase='prototype-validation',selected_for_study=False,
            prototype={'initial_context':'input-and-full-target-only','condition_ids':['ex','in-situ'],
                       'code_generation':'live-llm','step_generation':'live-llm','fixture_is_study_task':False})
        if not body.sources and s['input']==table(parse_table(prototype.INPUT)) and s['target']==table(parse_table(prototype.TARGET)):
            s['task_id']='prototype-check-orders'
        for item in s['events']:
            item.update(study_mode=prototype.MODE,condition_variant=condition_variant(s['condition'],prototype.MODE))
        event(s,'prototype_registered',{'initial_context':'input-and-full-target-only','selected_for_study':False})
        save(s);return view(s)


class Demo(BaseModel):
    correct: bool = False
    condition: str = 'in-situ'


@app.post('/api/demo')
def demo(body: Demo):
    s = create(Tables(input_csv=DEMO_INPUT, target_csv=DEMO_TARGET, requirements=DEMO_REQUIREMENTS,
                      task_id='orders-boundary-demo', condition=body.condition,execution_engine='capability'))
    s.pop('run', None)
    event(s, 'demo_loaded', {'fixture': 'correct' if body.correct else 'boundary-error', 'llm_generated': False})
    execute(s, demo_code(body.correct), ['데모: 사전 작성된 코드이며 LLM 생성 결과가 아닙니다.',
            'target은 현재 입력의 기대 출력입니다. 지역은 오름차순으로 정렬합니다.',
            '결측 그룹 키를 유지합니다. 합계는 pandas의 기본 결측 처리 규칙을 따릅니다.'], 'demo')
    event(s, 'execution_completed', {'source': 'demo'})
    save(s)
    return view(s)


@app.get('/api/sessions/{sid}')
def get_session(sid: str):
    with lock(sid):
        return view(read(sid))


@app.post('/api/demo/wrangling')
def wrangling_demo(body: Demo):
    s = create(Tables(input_csv=WRANGLING_INPUT, target_csv=WRANGLING_TARGET,
                      sources=WRANGLING_SOURCES, condition=body.condition, task_id='wrangling-demo',
                      requirements='완료 주문의 지역·월별 매출 합계. 잘못된 수량과 중복 주문을 제거하고 월을 열로 표시.',execution_engine='capability'))
    s.pop('run', None)
    execute(s, WRANGLING_CODE, ['데모: 사전 작성 코드. 실제 LLM 생성 결과가 아닙니다.', '고객 테이블의 지역을 사용하며, 피벗 이후 상세 계보는 미지원입니다.'], 'demo', groups=WRANGLING_STEPS)
    event(s, 'demo_loaded', {'fixture': 'extended-wrangling', 'llm_generated': False})
    save(s)
    return view(s)


class Generate(BaseModel):
    request: str | None = Field(default=None, max_length=5000)
    context: dict | None = None
    scope: str = 'pipeline'
    base_run_id: str | None = None


@app.post('/api/sessions/{sid}/generate')
def generate(sid: str, body: Generate):
    with lock(sid):
        s = read(sid)
        prev = current(s)
        revision = body.request is not None
        if s.get('study_mode')==prototype.MODE and not revision and body.context:
            raise HTTPException(422,'초기 생성에는 Input과 Target 외의 과제 설명을 전달할 수 없습니다.')
        if s.get('study_task') and not revision:
            raise HTTPException(409,'이 과제의 초기 코드는 고정되어 있습니다. 새 과제를 시작하거나 자연어 수정 요청을 사용하세요.')
        if revision and (not prev or not body.request.strip()):
            raise HTTPException(422, '수정할 실행 결과와 수정 요청이 필요합니다.')
        if body.scope not in ('step', 'pipeline'):
            raise HTTPException(422, '수정 범위를 확인하세요.')
        if body.base_run_id and (not prev or body.base_run_id != prev['id']):
            raise HTTPException(409, '기준 실행 버전이 달라졌습니다. 최신 실행을 다시 열어주세요.')
        target_id = (body.context or {}).get('step_id')
        if revision and body.scope == 'step' and not any(st['id'] == target_id for st in prev['stages'][1:]):
            raise HTTPException(422, '수정할 변환 Step을 선택하세요.')
        selected = next((st for st in (prev or {}).get('stages', []) if st['id'] == target_id), None)
        try:
            review = resolve_review_target(prev, body.context or {}, body.scope) if revision else None
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        model_context = {**(body.context or {}), 'scope': body.scope, 'base_run_id': prev['id'] if prev else None,
                         'pipeline': prev.get('pipeline') if prev else None, 'target_step': selected,
                         'cumulative_requirements': prev.get('cumulative_requirements', []) if prev else [],
                         'source_tables': s.get('sources_csv', {})}
        if review:
            target = review['target']
            model_context['review_target'] = review
            model_context['selection'] = ({'step': target['step_id'], 'row': target['row_id'],
                'column': target['column'], 'removed': target['removed'],
                'operation_id': target.get('operation_id')} if target['kind'] == 'cell' else None)
        started = time.perf_counter()
        attempt_id = str(uuid.uuid4())
        prefix = 'revision' if revision else 'generation'
        event(s, f'{prefix}_requested', {'request': body.request, 'context': body.context, 'scope': body.scope, 'base_run_id': prev['id'] if prev else None, 'review_ms': review_duration(s), 'attempt_id': attempt_id})
        s.update(status='generating', error=None, confirmed=None)
        save(s)
        phase, proposal, plan = 'generation', None, None
        try:
            if revision and prev['mode'] == 'demo':
                proposal = revise_demo(prev['code'], body.request)
                mode = 'demo'
            else:
                proposal = generator.generate(s['input_csv'], s['target_csv'], '' if s.get('study_mode')==prototype.MODE else s['requirements'],
                                              prev['code'] if revision else None, body.request, model_context)
                mode = 'api'
            event(s, f'{prefix}_completed', {'generation_ms': round((time.perf_counter() - started) * 1000, 2),
                  'candidate_code': proposal.code, 'proposal': proposal.model_dump(), 'assumptions': proposal.assumptions, 'mode': mode, 'attempt_id': attempt_id})
            if s.get('study_mode')==prototype.MODE and not revision and not proposal.steps:
                raise ValueError('모델이 의미 Step을 반환하지 않았습니다. 코드와 Step을 함께 다시 생성하세요.')
            phase = 'execution'
            plan = patch(prev, proposal.changes, proposal.base_run_id, body.scope, target_id) if proposal.changes else prepare(proposal.code, proposal.steps or None, prev,engine=s.get('execution_engine','capability'))
            if revision:
                validate_scope(plan, prev, body.scope, target_id)
            event(s, 'revision_execution_started' if revision else 'execution_started', {'attempt_id': attempt_id})
            r = execute(s, plan['code'], proposal.assumptions, mode, body.request, prepared=plan)
            if review:
                r['review_comment'] = {'target': review['target'], 'request': body.request,
                    'scope': body.scope, 'base_run_id': prev['id'], 'base_code_version': prev['code_version'],
                    'interaction': 'selection-action-v2' if (body.context or {}).get('interaction') == 'selection-action-v2' else 'anchored-comment-v1'}
            event(s, 'revision_execution_completed' if revision else 'execution_completed',
                  {'execution_ms': r['execution_ms'], 'processing_ms': round((time.perf_counter() - started) * 1000, 2), 'attempt_id': attempt_id})
        except Exception as exc:
            s.update(status='failed', error={'phase': phase, 'message': str(exc)[:2000],
                     'candidate_code': plan['code'] if plan else proposal.code if proposal else None,
                     'candidate_proposal': proposal.model_dump() if proposal else None, 'at': now(), 'attempt_id': attempt_id})
            s['error'].update(failure=getattr(exc,'failure',{}),partial_stages=partial_stages(exc,plan,attempt_id))
            s.setdefault('failed_attempts',[]).append(dict(s['error']))
            event(s, f'{prefix}_execution_failed' if phase == 'execution' else f'{prefix}_failed',
                  {'phase': phase, 'message': s['error']['message'], 'processing_ms': round((time.perf_counter() - started) * 1000, 2), 'attempt_id': attempt_id,
                   'last_success_run_id': current(s)['id'] if current(s) else None})
        save(s)
        return view(s)


class EventBody(BaseModel):
    event: str
    data: dict = Field(default_factory=dict)
    execution_version: str | None = None
    condition: str | None = None


@app.post('/api/sessions/{sid}/events')
def log(sid: str, body: EventBody):
    allowed = {'review_started', 'step_selected', 'row_selected', 'cell_selected', 'column_selected', 'review_target_selected', 'review_comment_opened', 'lineage_viewed', 'removed_rows_expanded', 'workspace_view_changed', 'workflow_layout_changed'}
    if body.event not in allowed or len(json.dumps(body.data)) > 10000:
        raise HTTPException(422, '지원하지 않는 이벤트입니다.')
    with lock(sid):
        s = read(sid)
        r = next((r for r in s['runs'] if r['id'] == body.execution_version), None) if body.execution_version else current(s)
        event_condition = active_condition(body.condition or s['condition'])
        if event_condition not in CONDITION_VARIANTS or (body.execution_version and not r):
            raise HTTPException(422, '존재하지 않는 실행 버전입니다.')
        if body.event == 'review_started' and any(e['event'] == 'review_started' and e['execution_version'] == (r['id'] if r else None) and e['condition'] == event_condition for e in s['events']):
            return {'ok': True}
        event(s, body.event, body.data)
        s['events'][-1].update(execution_version=r['id'] if r else None, code_version=r['code_version'] if r else None,
                               condition=event_condition, condition_variant=condition_variant(event_condition))
        save(s)
    return {'ok': True}


class Condition(BaseModel):
    condition: str


@app.post('/api/sessions/{sid}/condition')
def condition(sid: str, body: Condition):
    if body.condition not in CONDITION_VARIANTS:
        raise HTTPException(422, '잘못된 조건입니다.')
    with lock(sid):
        s = read(sid)
        if s.get('study_mode')==prototype.MODE and body.condition not in prototype.CONDITIONS:
            raise HTTPException(422,'프로토타입은 Ex-situ와 In-situ 두 조건만 지원합니다.')
        old = s['condition']
        s['condition'] = body.condition
        s['condition_variant'] = condition_variant(body.condition,s.get('study_mode'))
        event(s, 'condition_changed', {'from': old, 'to': body.condition, 'regenerated': False})
        save(s)
        return view(s)


@app.post('/api/sessions/{sid}/undo')
def undo(sid: str):
    with lock(sid):
        s = read(sid)
        r = current(s)
        if s['status'] == 'failed' and r:
            s.update(status='ready', error=None, confirmed=None)
        elif r and r.get('parent_run_id'):
            s['cursor'] = next(i for i, v in enumerate(s['runs']) if v['id'] == r['parent_run_id'])
            s.update(status='ready', error=None, confirmed=None)
        else:
            raise HTTPException(422, '되돌릴 실행이 없습니다.')
        event(s, 'undo', {'from_run_id': r['id'] if r else None, 'to_run_id': current(s)['id']})
        event(s, 'review_resumed')
        save(s)
        return view(s)


@app.post('/api/sessions/{sid}/confirm')
def confirm(sid: str):
    with lock(sid):
        s = read(sid)
        if s['status'] != 'ready' or not current(s):
            raise HTTPException(422, '현재 성공한 실행 결과가 있어야 확정할 수 있습니다.')
        if not s['confirmed']:
            s['confirmed'] = {'at': now(), 'run_id': current(s)['id']}
            event(s, 'final_confirmed', {'review_ms': review_duration(s), 'output': current(s)['stages'][-1]['table'], 'code': current(s)['code']})
            save(s)
        return view(s)


class Code(BaseModel):
    code: str = Field(max_length=30000)
    assumptions: list[str] = Field(default_factory=lambda: ['연구자가 등록한 코드입니다.'])
    steps: list[dict] | None = None
    execution_engine: str | None=None
    structure_with_llm: bool=False


@app.post('/api/sessions/{sid}/research-code')
def research_code(sid: str, body: Code):
    with lock(sid):
        s = read(sid)
        plan=None
        attempt_id=str(uuid.uuid4())
        try:
            engine=body.execution_engine or s.get('execution_engine','capability')
            if engine not in ('python','capability'):raise ValueError('잘못된 실행기')
            groups=body.steps;assumptions=body.assumptions
            if body.structure_with_llm and not groups:
                proposal=generator.structure(body.code,{'input':s['input'],'requirements':s['requirements']})
                groups=proposal.steps;assumptions=assumptions+proposal.assumptions
                event(s,'code_structure_completed',{'code_unchanged':True,'source':'llm_annotations','model':os.getenv('OPENAI_MODEL',DEFAULT_MODEL)})
            plan=prepare(body.code,groups,current(s),engine=engine)
            execute(s, body.code, assumptions, 'research',prepared=plan)
            s['execution_engine']=engine
            event(s, 'research_code_loaded')
        except Exception as exc:
            s.update(status='failed', confirmed=None, error={'phase': 'execution', 'message': str(exc), 'candidate_code': body.code, 'at': now(),'attempt_id':attempt_id})
            s['error'].update(failure=getattr(exc,'failure',{}),partial_stages=partial_stages(exc,plan,attempt_id))
            s.setdefault('failed_attempts',[]).append(dict(s['error']))
            event(s, 'execution_failed', {'message': str(exc)})
        save(s)
        return view(s)


@app.get('/api/sessions/{sid}/export')
def export(sid: str):
    with lock(sid):
        s = read(sid)
        payload = json.dumps({**s, 'exported_at': now(), 'final_code': current(s)['code'] if current(s) else None,
                              'final_output': current(s)['stages'][-1]['table'] if current(s) else None}, ensure_ascii=False, indent=2)
    return Response(payload, media_type='application/json', headers={'Content-Disposition': f'attachment; filename="trace-{sid}.json"'})


@app.get('/api/sessions/{sid}/output.csv')
def output_csv(sid: str):
    with lock(sid):
        s = read(sid)
        if not current(s):
            raise HTTPException(422, '실행 결과가 없습니다.')
        import pandas as pd
        out = current(s)['stages'][-1]['table']
        frame = pd.DataFrame([r['values'] for r in out['rows']], columns=out['columns'])
        return Response('\ufeff' + frame.to_csv(index=False), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="output.csv"'})


class Replay(BaseModel):
    session: dict
    condition: str = 'in-situ'
    run_index: int = 0


@app.post('/api/replay')
def replay(body: Replay):
    original = body.session
    try:
        saved_run = original['runs'][body.run_index]
        s = create(Tables(input_csv=original['input_csv'], target_csv=original['target_csv'],
                          requirements=original.get('requirements', ''), task_id=original.get('task_id', 'replay'), condition=body.condition, sources=original.get('sources_csv', {}),execution_engine=saved_run.get('pipeline',{}).get('engine',original.get('execution_engine','capability'))))
        s.pop('run', None)
        specs = [{'statement_indices': st['statement_indices'], 'label': st.get('intent_label', ''),'output_variable':st.get('output_variable')} for st in saved_run.get('pipeline', {}).get('steps', [])] or None
        execute(s, saved_run['code'], saved_run.get('assumptions', []), saved_run.get('mode', 'research'), groups=specs)
        s['replayed_from'] = {'session_id': original.get('id'), 'run_id': saved_run.get('id'), 'run_index': body.run_index}
        event(s, 'replay_loaded', s['replayed_from'])
        save(s)
        return view(s)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise HTTPException(422, f'재현 파일을 읽을 수 없습니다: {exc}')


class CandidateLoad(BaseModel):
    condition: str = 'in-situ'
    variant: str = 'initial'


@app.get('/api/task-candidates')
def list_task_candidates(full: bool=False):
    try:
        return candidates.listing(include_disabled=full)
    except (ValueError,OSError) as exc:
        raise HTTPException(422,str(exc))


@app.post('/api/task-candidates/{cid}/load')
def load_task_candidate(cid: str,body: CandidateLoad):
    if body.variant not in ('initial','reference'):
        raise HTTPException(422,'잘못된 과제 코드 종류입니다.')
    if cid.startswith('VERIFY2-') and body.variant=='initial':
        return start_study(cid,StudyStart(condition=active_condition(body.condition)),preview=True,woz=True)
    try:
        c=candidates.load(cid)
    except (ValueError,OSError) as exc:
        raise HTTPException(404,str(exc))
    if body.variant=='reference' and not c.get('reference_code'):
        raise HTTPException(422,'이 과제에는 참조 코드가 등록되어 있지 않습니다.')
    s=create(Tables(input_csv=c['input_csv'],target_csv=c['target_csv'],sources=c.get('sources',{}),
        requirements=c['description'],task_id=c['id'],condition=body.condition,execution_engine='python'))
    code=c['initial_code'] if body.variant=='initial' else c['reference_code']
    groups=c.get('reference_steps',c['steps']) if body.variant=='reference' else c['steps']
    research_code(s['id'],Code(code=code,steps=groups,assumptions=[],execution_engine='python'))
    s=read(s['id'])
    s['task_display']={'title':c['title'],'review_number':c.get('review_number')}
    s['task_provenance']={**c['provenance'],'candidate_variant':body.variant,
        'loaded_origin':c['provenance']['initial_origin'] if body.variant=='initial' else 'authored_reference'}
    event(s,'task_candidate_loaded',{'candidate_id':cid,'variant':body.variant})
    save(s)
    return view(s)


class CandidateRegistration(BaseModel):
    candidate: dict


@app.post('/api/task-candidates/register')
def register_candidate(body: CandidateRegistration):
    try:
        cid=candidates.register(body.candidate)
        return {'id':cid,'participant_enabled':False}
    except FileExistsError:
        raise HTTPException(409,'같은 ID의 과제가 있습니다. 새 ID로 등록하세요.')
    except (ValueError,TypeError,KeyError,OSError) as exc:
        raise HTTPException(422,str(exc))


class CandidatePublication(BaseModel):
    visible: bool


@app.post('/api/task-candidates/{cid}/publication')
def publish_candidate(cid: str,body: CandidatePublication):
    try:
        candidates.publish(cid,body.visible)
        return {'id':cid,'participant_enabled':body.visible}
    except (ValueError,OSError) as exc:
        raise HTTPException(422,str(exc))


def study_input(cid,preview=False):
    who=request_identity.get() or {}
    if who.get('pilot') and not preview:
        state=assigned_state()
        if not state['current'] or state['current']['task_id']!=cid:raise HTTPException(403,'현재 배정된 과제만 열 수 있습니다.')
    try:
        c=candidates.load(cid)
        if not preview and not candidates.available(c):raise ValueError('사용할 수 있는 과제가 아닙니다.')
        return {**candidates.study_summary(c),'input_csv':c['input_csv'],'input':table(parse_table(c['input_csv'])),
                'target_csv':c['target_csv'],'target':table(parse_table(c['target_csv'])),
                'sources':{name:table(parse_table(csv)) for name,csv in c.get('sources',{}).items()}}
    except (ValueError,OSError) as exc:
        raise HTTPException(404,str(exc))


@app.get('/api/study-tasks')
def study_tasks():
    try:
        if (request_identity.get() or {}).get('pilot'):
            state=assigned_state()
            return [candidates.study_summary(candidates.load(state['current']['task_id']))] if state['current'] else []
        return candidates.study_listing()
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc))


@app.get('/api/study-tasks/{cid}/input')
def get_study_input(cid: str):
    return study_input(cid)


@app.get('/api/task-candidates/{cid}/input')
def preview_study_input(cid: str):
    return study_input(cid,preview=True)


class StudyStart(BaseModel):
    condition: str='in-situ'
    input_csv: str | None=Field(default=None,max_length=1_000_000)
    target_csv: str | None=Field(default=None,max_length=1_000_000)


def start_study(cid,body,preview=False,assignment=None,woz=False):
    if (request_identity.get() or {}).get('pilot') and not assignment:
        raise HTTPException(403,'배정된 과제 시작 버튼을 사용하세요.')
    try:
        c=candidates.load(cid)
        if not preview and not candidates.available(c):raise ValueError('사용할 수 있는 과제가 아닙니다.')
        if body.input_csv is not None and not parse_table(body.input_csv).equals(parse_table(c['input_csv'])):
            raise ValueError('이 과제의 Input과 다른 데이터입니다. 과제에서 제공한 원본 Input을 사용하세요.')
        if body.target_csv is not None and not parse_table(body.target_csv).equals(parse_table(c['target_csv'])):
            raise ValueError('이 과제의 Target과 다른 데이터입니다. 과제에서 제공한 원본 Target을 사용하세요.')
    except (ValueError,OSError) as exc:
        raise HTTPException(422,str(exc))
    summary=candidates.study_summary(c)
    registered=create(Tables(input_csv=c['input_csv'],target_csv=c['target_csv'],sources=c.get('sources',{}),
        requirements='' if woz else summary['description'],task_id=cid,condition=body.condition,execution_engine='python'))
    with lock(registered['id']):
        s=read(registered['id'])
        if assignment:
            s['assignment']=assignment
            for e in s['events']:e.update(assignment_id=assignment['id'],plan_version=assignment['plan_version'])
        s['study_task']={'id':cid,'title':summary['title'],'review_number':c.get('review_number'),'fixed_input':True,'target_visibility':'participant'}
        if woz:
            s.update(study_mode='woz-v1',research_phase='task-screening',selected_for_study=False)
        s['task_display']={'title':summary['title'],'review_number':c.get('review_number')}
        for e in s['events']:e['review_number']=c.get('review_number')
        digest=hashlib.sha256(json.dumps({**{k:c[k] for k in ('input_csv','target_csv','initial_code','steps')},'sources':c.get('sources',{})},
            ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        s['task_provenance']={**c['provenance'],'candidate_variant':'initial',
            'loaded_origin':c['provenance']['initial_origin'],'snapshot_sha256':digest,'initial_model_called':False}
        if woz:
            artifacts={**{key:c[key] for key in ('input_csv','target_csv','initial_code','steps')},'sources':c.get('sources',{})}
            s['task_provenance']['artifact_sha256']={key:hashlib.sha256((value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True)).encode()).hexdigest() for key,value in artifacts.items()}
        event(s,'study_task_started',{'initial_source':'stored_code','model_called':False,
            'snapshot_sha256':digest,'researcher_preview':preview,'presentation':'woz-v1' if woz else 'task-entry-v1','presentation_minimum_ms':1200})
        s['status']='executing';save(s)
        plan=None;attempt_id=str(uuid.uuid4())
        try:
            plan=prepare(c['initial_code'],c['steps'],engine='python')
            execute(s,c['initial_code'],[],'research',prepared=plan)
            if woz:judgments.initialize(s,current(s),c.get('researcher_notes',{}).get('fault_steps'))
            event(s,'execution_completed',{'source':'stored_code','model_called':False})
        except Exception as exc:
            s.update(status='failed',error={'phase':'execution','message':str(exc),'candidate_code':c['initial_code'],
                'attempt_id':attempt_id,'at':now(),'partial_stages':partial_stages(exc,plan,attempt_id)})
            event(s,'execution_failed',{'source':'stored_code','message':str(exc)})
        save(s)
        return view(s)


@app.post('/api/study-tasks/{cid}/start')
def start_study_task(cid: str,body: StudyStart):
    return start_study(cid,body)


@app.post('/api/task-candidates/{cid}/start')
def preview_study_task(cid: str,body: StudyStart):
    return start_study(cid,body,preview=True)


def woz_preview():
    return (request_identity.get() or {}).get('role') != 'participant'


@app.get('/api/woz-tasks')
def woz_tasks():
    # Participant catalog never exposes error notes, provenance or stored code.
    items=candidates.listing() if woz_preview() else candidates.study_listing()
    allowed={'id','title','review_number'} | ({'initial_origin'} if woz_preview() else set())
    return [{key:value for key,value in item.items() if key in allowed}
            for item in items if item.get('enabled',True)]


@app.get('/api/woz-tasks/{cid}/input')
def woz_input(cid: str):
    result=study_input(cid,preview=woz_preview())
    return {key:value for key,value in result.items() if key!='description'}


class WozStart(StudyStart):
    model_config={'extra':'forbid'}
    input_csv: str=Field(min_length=1,max_length=1_000_000)
    target_csv: str=Field(min_length=1,max_length=1_000_000)


@app.post('/api/woz-tasks/{cid}/start')
def start_woz(cid: str,body: WozStart):
    if body.condition not in CONDITION_VARIANTS:raise HTTPException(422,'조건은 ex 또는 in-situ여야 합니다.')
    return start_study(cid,body,preview=woz_preview(),woz=True)


@app.post('/api/sessions/{sid}/initial-step-judgment')
def initial_step_judgment(sid:str,body:judgments.Judgment):
    payload=body.model_dump(mode='json')
    with lock(sid):
        s=read(sid)
        old=next((item for item in s.get('initial_step_judgments',[]) if item['submission_id']==payload['submission_id']),None)
        if old:
            if any(old.get(key)!=value for key,value in payload.items()):raise HTTPException(409,'같은 제출 번호로 다른 응답을 보낼 수 없습니다.')
            return {'ok':True,'judgment':old}
        r=current(s)
        if not r:raise HTTPException(409,'검수할 실행 결과가 없습니다.')
        try:evaluation=judgments.evaluate(s,payload,r)
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
        response={**payload,'at':now(),'code_version':r['code_version']}
        s.setdefault('initial_step_judgments',[]).append(response)
        s.setdefault('judgment_evaluations',[]).append({**evaluation,'at':response['at']})
        event(s,'initial_step_judgment_submitted',payload)
        save(s)
        return {'ok':True,'judgment':response}


@app.post('/api/sessions/{sid}/feedback')
def pilot_feedback(sid: str,body: Feedback):
    payload=body.model_dump(mode='json')
    with lock(sid):
        s=read(sid)
        existing=next((f for f in s.get('feedbacks',[]) if f['submission_id']==payload['submission_id']),None)
        if existing:
            if any(existing.get(k,[] if k=='issue_types' else None)!=v for k,v in payload.items()):
                raise HTTPException(409,'같은 제출 번호로 다른 응답을 보낼 수 없습니다.')
            return {'ok':True,'feedback':existing}
        r=current(s)
        if payload['condition']!=s['condition'] or payload['execution_version']!=(r['id'] if r else None):
            raise HTTPException(409,'실행 버전이나 조건이 바뀌었습니다. 현재 화면에서 피드백을 다시 열어주세요.')
        f={**payload,'at':now(),'participant_id':s.get('participant_id'),
           'assignment_id':s.get('assignment',{}).get('id'),'plan_version':s.get('assignment',{}).get('plan_version'),
           'questionnaire_version':'pilot-task-screening-v2','code_version':r['code_version'] if r else None,
           'status_at_submission':s['status'],'failed_attempt_id':(s.get('error') or {}).get('attempt_id'),
           'actor_id':(request_identity.get() or {}).get('name','local'),
           'session_id':sid,'task_id':s['task_id'],'review_number':s.get('task_display',{}).get('review_number')}
        s.setdefault('feedbacks',[]).append(f)
        event(s,'pilot_feedback_submitted',{'submission_id':f['submission_id'],'questionnaire_version':'pilot-task-screening-v2'})
        save(s)
        return {'ok':True,'feedback':f}


class ExplainRun(BaseModel):
    run_id: str


@app.post('/api/sessions/{sid}/explanations')
def explain_run(sid: str,body: ExplainRun):
    with lock(sid):
        s=read(sid);r=current(s)
        if not r or r['id']!=body.run_id:raise HTTPException(409,'실행 버전이 바뀌었습니다. 현재 실행을 다시 여세요.')
        if r.get('explanation_status')=='ready' and r.get('explanation_meta',{}).get('fingerprint')==explanations.fingerprint(r):return view(s)
        snapshot=json.loads(json.dumps(r,ensure_ascii=False))
    try:bundle,cached=explanations.obtain(snapshot);failure=None
    except Exception as exc:bundle=None;cached=False;failure=str(exc)[:500]
    with lock(sid):
        s=read(sid);r=current(s)
        if not r or r['id']!=body.run_id:raise HTTPException(409,'설명 준비 중 실행 버전이 바뀌었습니다. 현재 실행을 다시 여세요.')
        if bundle and r.get('explanation_status')=='ready' and r.get('explanation_meta',{}).get('fingerprint')==bundle['fingerprint']:return view(s)
        if bundle:
            explanations.attach(r,bundle,cached)
            event(s,'step_explanations_ready',{'source':'llm','model':bundle['model'],'prompt_version':bundle['prompt_version'],
                'fingerprint':bundle['fingerprint'],'cache_hit':cached})
        else:
            r['explanation_status']='failed';r['explanation_error']=failure
            event(s,'step_explanations_failed',{'message':failure})
        save(s)
        return view(s)


def pilot_session_records():
    # Session files are atomically replaced. Existing anonymous sessions are not
    # retroactively assigned to a person; exports include named pilot accounts.
    for file in STORE.glob('*.json'):
        s=json.loads(file.read_text(encoding='utf-8'))
        if s.get('pilot_account') and s.get('participant_id'):
            yield s


def assigned_state():
    who=request_identity.get() or {}
    if not who.get('pilot'):raise HTTPException(403,'개별 파일럿 계정으로 로그인하세요.')
    sessions=list(pilot_session_records())
    state=pilot_progress(who['participant_id'],sessions)
    if not state['total']:raise HTTPException(403,'이 계정에는 배정된 과제가 없습니다.')
    state=pilot_progress(who['participant_id'],sessions,{item['id'] for item in candidates.study_listing()})
    return state


@app.get('/api/pilot-assignment')
def get_assignment():
    state=assigned_state()
    if state['current']:state['task']=candidates.study_summary(candidates.load(state['current']['task_id']))
    return state


@app.get('/api/pilot-assignment/input')
def assignment_input():
    state=assigned_state()
    if not state['current']:raise HTTPException(409,'모든 배정 과제를 완료했습니다.')
    return {**study_input(state['current']['task_id']),'assignment':state['current']}


class AssignedStart(BaseModel):
    input_csv: str | None=Field(default=None,max_length=1_000_000)


@app.post('/api/pilot-assignment/start')
def start_assignment(body: AssignedStart):
    who=request_identity.get() or {}
    if not who.get('pilot'):raise HTTPException(403,'개별 파일럿 계정으로 로그인하세요.')
    with lock('pilot-assignment:'+who['participant_id']):
        state=assigned_state()
        if not state['current']:raise HTTPException(409,'모든 배정 과제를 완료했습니다.')
        if state['session_id']:
            with lock(state['session_id']):return view(read(state['session_id']))
        a=state['current']
        return start_study(a['task_id'],StudyStart(condition=a['condition'],input_csv=body.input_csv),assignment=a)


@app.get('/api/my-sessions')
def my_sessions():
    who=request_identity.get() or {}
    pid=who.get('participant_id')
    rows=[session_summary(s) for s in pilot_session_records() if pid and s['participant_id']==pid]
    return {'participant_id':pid,'sessions':sorted(rows,key=lambda s:s['started_at'],reverse=True)}


@app.get('/api/pilot/summary')
def pilot_summary():
    return {'sessions':sorted([session_summary(s) for s in pilot_session_records()],key=lambda s:s['started_at'],reverse=True)}


@app.get('/api/pilot/export/{kind}')
def pilot_export(kind: str):
    sessions=list(pilot_session_records())
    if kind=='events.jsonl':
        content=''.join(json.dumps(e,ensure_ascii=False)+'\n' for s in sessions for e in s['events'])
        media='application/x-ndjson'
    elif kind=='sessions.csv':
        content=csv_text([session_summary(s) for s in sessions]);media='text/csv; charset=utf-8'
    elif kind=='feedback.csv':
        content=csv_text([{**f,'issue_types':f.get('issue_types',[])} for s in sessions for f in s.get('feedbacks',[])]);media='text/csv; charset=utf-8'
    else:raise HTTPException(404,'지원하지 않는 내보내기 형식입니다.')
    return Response(content,media_type=media,headers={'Content-Disposition':f'attachment; filename="trace-pilot-{kind}"'})


class DiscardItem(BaseModel):
    session_id: uuid.UUID
    last_event_id: str | None=None


class DiscardPilot(BaseModel):
    sessions: list[DiscardItem]=Field(min_length=1,max_length=100)


@app.post('/api/pilot/discard')
def discard_pilot(body: DiscardPilot):
    items={str(item.session_id):item.last_event_id for item in body.sessions}
    if len(items)!=len(body.sessions):raise HTTPException(422,'세션 번호가 중복되었습니다.')
    with ExitStack() as stack:
        for sid in sorted(items):stack.enter_context(lock(sid))
        for sid,expected in items.items():
            s=read(sid)
            if not s.get('pilot_account') or not s.get('participant_id'):
                raise HTTPException(422,'개별 파일럿 계정의 기록만 삭제할 수 있습니다.')
            actual=s['events'][-1]['id'] if s['events'] else None
            if expected!=actual:
                raise HTTPException(409,'선택한 기록에 새 활동이 있습니다. 새로고침 후 다시 선택하세요.')
        batch=str(uuid.uuid4())
        folder=STORE.parent/'deleted_sessions'/batch
        folder.mkdir(parents=True)
        (folder/'manifest.json').write_text(json.dumps({'at':now(),'actor_id':(request_identity.get() or {}).get('name','local'),
            'session_ids':list(items)},ensure_ascii=False),encoding='utf-8')
        moved=[]
        try:
            for sid in items:
                path(sid).replace(folder/f'{sid}.json');moved.append(sid)
        except OSError:
            for sid in moved:(folder/f'{sid}.json').replace(path(sid))
            raise
    return {'ok':True,'discarded':list(items),'recovery_batch':batch}


@app.middleware('http')
async def local_guard(request: Request, call_next):
    denied = await gate(request)
    if denied is not None:
        denied.headers['Cache-Control'] = 'no-store'
        denied.headers['X-Content-Type-Options'] = 'nosniff'
        return denied
    # This prototype stores research datasets locally; reject cross-origin writes.
    origin = request.headers.get('origin')
    same_origin=str(request.base_url).rstrip('/')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin != same_origin and origin not in origins(request.state.access_config):
        return Response('허용되지 않은 출처입니다.', status_code=403)
    try:
        length = int(request.headers.get('content-length', '0'))
    except ValueError:
        return Response('잘못된 Content-Length입니다.',status_code=400)
    if length > 25_000_000:
        return Response('요청 크기가 너무 큽니다.', status_code=413)
    identity_token=request_identity.set(request.state.access_identity)
    try:
        response = await call_next(request)
    finally:
        request_identity.reset(identity_token)
    if (request.state.access_role=='participant' or request.headers.get('x-trace-view')=='participant') and response.headers.get('content-type','').startswith('application/json'):
        chunks=[chunk async for chunk in response.body_iterator]
        data=json.loads(b''.join(chunks))
        headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'}
        response=Response(json.dumps(participant_view(data),ensure_ascii=False),status_code=response.status_code,headers=headers,media_type='application/json')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if request.state.access_config:
        response.headers['Cache-Control'] = 'no-store'
    return response


if (ROOT / 'dist' / 'assets').exists():
    app.mount('/assets', StaticFiles(directory=ROOT / 'dist' / 'assets'), name='assets')


@app.get('/')
def index():
    if not (ROOT / 'dist' / 'index.html').exists():
        raise HTTPException(503, 'npm run build 후 서버를 시작하거나 Vite 개발 서버를 사용하세요.')
    return FileResponse(ROOT / 'dist' / 'index.html')
