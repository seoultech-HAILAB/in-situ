"""Bundled research fixtures with a writable local catalog."""
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from .pilot_plan import EXCLUDED_TASK_IDS
from .task_diagnostics import diagnostics

ROOT=Path(__file__).resolve().parent.parent
catalog_lock=threading.RLock()


def directory():
    configured=os.getenv('TRACE_TASK_DIR')
    if configured:return Path(configured)
    folder=ROOT/'.local/pilot/candidates'
    # Import new bundles even into installations created by an older checkout.
    # Update only untouched managed files. Local edits and deliberate deletions
    # are retained; an explicit TRACE_TASK_DIR never receives bundled fixtures.
    with catalog_lock:
        folder.mkdir(parents=True,exist_ok=True)
        marker=folder/'.bundled-catalog.json'
        installed=json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else {}
        updated=dict(installed)
        for source in sorted((ROOT/'tasks/candidates').glob('*.json')):
            raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            previous=installed.get(source.name)
            if previous==sha:continue
            dest=folder/source.name
            if (not dest.exists() and previous is None) or (dest.exists() and previous and hashlib.sha256(dest.read_bytes()).hexdigest()==previous):
                temp=dest.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(dest)
            updated[source.name]=sha
        if updated!=installed or not marker.exists():
            temp=marker.with_suffix('.tmp');temp.write_text(json.dumps(updated,sort_keys=True),encoding='utf-8');temp.replace(marker)
    return folder


def load(cid):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',cid):
        raise ValueError('과제 후보를 찾을 수 없습니다.')
    file=directory()/(cid+'.json')
    if not file.exists() or file.stat().st_size>3_000_000:
        raise ValueError('과제 후보를 찾을 수 없습니다.')
    data=json.loads(file.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or data.get('id')!=cid or not all(k in data for k in ('title','description','input_csv','target_csv','initial_code','steps')):
        raise ValueError('과제 후보 형식이 올바르지 않습니다.')
    if any(not isinstance(data[k],str) for k in ('title','description','input_csv','target_csv','initial_code')) or not isinstance(data['steps'],list):
        raise ValueError('과제의 텍스트와 Step 정보 형식을 확인하세요.')
    if not isinstance(data.get('provenance',{}),dict) or not isinstance(data.get('researcher_notes',{}),dict):
        raise ValueError('과제 출처와 연구자 기록 형식을 확인하세요.')
    data['provenance']={'initial_origin':'stored_code','original_task_id':cid,'actual_luna_program':None,**data.get('provenance',{})}
    return data


def listing(include_disabled=False):
    result=[]
    for file in sorted(directory().glob('*.json')):
        if file.stem=='validation' or file.name.startswith('.'):continue
        try:c=load(file.stem)
        except (ValueError,OSError):
            if include_disabled:result.append({'id':file.stem,'title':'과제 파일 형식 확인 필요','description':'필수 필드·JSON 형식을 확인한 뒤 다시 불러오세요.',
                'initial_origin':'invalid','original_task_id':file.stem,'trace_levels':[],'steps':0,
                'enabled':False,'participant_enabled':False,'has_reference_code':False})
            continue
        if c['id'] in EXCLUDED_TASK_IDS or c.get('researcher_notes',{}).get('excluded_from_pilot'):continue
        if not include_disabled and not c.get('enabled',True):continue
        result.append({'id':c['id'],'title':c['title'],'initial_origin':c['provenance']['initial_origin'],
            'original_task_id':c['provenance'].get('original_task_id',c['id']),
            'trace_levels':c.get('researcher_notes',{}).get('initial_trace_levels',[]),
            'steps':len(c['steps']), 'enabled':c.get('enabled',True) is True,
            'participant_enabled':c.get('participant_enabled',False) is True,
            'has_reference_code':bool(c.get('reference_code')), 'description':c['description']})
        result[-1].update(review_number=c.get('review_number'),review_notes=c.get('researcher_notes',{}).get('review_csv',{}))
        notes=c.get('researcher_notes',{})
        result[-1]['diagnostics']=diagnostics(c)
        result[-1]['screening']={key:notes[key] for key in ('pair','variant','level','step_metrics') if key in notes}
        context=c['provenance'].get('source_generation_context',{})
        if isinstance(context,dict) and isinstance(context.get('input_condition'),str):result[-1]['screening']['source_input_condition']=context['input_condition']
    return result


def study_summary(c):
    # Explicit allowlist: never publish provenance, code, Step metadata, Target,
    # stored output, error commentary or researcher notes in the task catalog.
    summary={'id':c['id'],'title':c.get('participant_title') or c['title'],
             'description':c.get('participant_description') or c['description']}
    if type(c.get('review_number')) is int:summary['review_number']=c['review_number']
    return summary


def available(c):
    return c['id'] not in EXCLUDED_TASK_IDS and not c.get('researcher_notes',{}).get('excluded_from_pilot') and c.get('enabled',True) is True and c.get('participant_enabled',False) is True


def study_listing():
    return [study_summary(c) for item in listing() if available(c:=load(item['id']))]


def publish(cid, visible):
    with catalog_lock:
        c=load(cid)
        if visible and (cid in EXCLUDED_TASK_IDS or c.get('researcher_notes',{}).get('excluded_from_pilot')):
            raise ValueError('파일럿에서 제외된 과제는 공개할 수 없습니다.')
        if visible and c.get('enabled',True) is not True:raise ValueError('비활성 과제는 공개할 수 없습니다.')
        c['participant_enabled']=visible
        file=directory()/(cid+'.json')
        temp=file.with_suffix('.tmp')
        temp.write_text(json.dumps(c,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        temp.replace(file)


def register(data):
    from .engine import parse_table
    from .pipeline import prepare
    if not isinstance(data,dict):raise ValueError('과제 JSON 객체가 필요합니다.')
    cid=data.get('id','')
    if not isinstance(cid,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',cid):
        raise ValueError('과제 ID는 영문·숫자·하이픈·밑줄, 최대 64자입니다.')
    for key,limit in [('title',200),('description',5000),('input_csv',1_000_000),('target_csv',1_000_000),('initial_code',30000)]:
        if not isinstance(data.get(key),str) or not data[key].strip() or len(data[key])>limit:
            raise ValueError(f'{key} 값 또는 크기를 확인하세요.')
    parse_table(data['input_csv']);parse_table(data['target_csv'])
    sources=data.get('sources',{})
    if not isinstance(sources,dict) or len(sources)>4:raise ValueError('추가 입력은 최대 4개입니다.')
    for name,csv in sources.items():
        if not isinstance(name,str) or not name.isidentifier() or name.startswith('_') or name=='input':
            raise ValueError('추가 입력의 이름을 확인하세요.')
        if not isinstance(csv,str) or len(csv)>1_000_000:raise ValueError('추가 입력 크기를 확인하세요.')
        parse_table(csv)
    if not isinstance(data.get('steps'),list) or not data['steps'] or not all(isinstance(step,dict) for step in data['steps']):raise ValueError('Step 정보가 필요합니다.')
    prepare(data['initial_code'],data['steps'],engine='python')
    if data.get('reference_code'):
        if not isinstance(data['reference_code'],str) or len(data['reference_code'])>30000:raise ValueError('참조 코드 크기를 확인하세요.')
        prepare(data['reference_code'],engine='python')
    provenance=data.get('provenance')
    if provenance is not None and not isinstance(provenance,dict):raise ValueError('provenance는 JSON 객체여야 합니다.')
    saved={**data,'enabled':True,'participant_enabled':False,
           'provenance':{'initial_origin':'stored_code','original_task_id':cid,'actual_luna_program':None,**(provenance or {})}}
    if not isinstance(saved['provenance']['initial_origin'],str):raise ValueError('초기 코드 출처 형식을 확인하세요.')
    if not isinstance(saved.get('researcher_notes',{}),dict):raise ValueError('researcher_notes는 JSON 객체여야 합니다.')
    faults=saved.get('researcher_notes',{}).get('fault_steps')
    if faults is not None and (not isinstance(faults,list) or any(type(n) is not int or not 1<=n<=len(data['steps']) for n in faults) or len(faults)!=len(set(faults))):
        raise ValueError('fault_steps는 초기 의미 Step 순서의 중복 없는 목록이어야 합니다.')
    levels=saved.get('researcher_notes',{}).get('initial_trace_levels',[])
    if not isinstance(levels,list) or any(v not in ('detailed','common','partial') for v in levels):
        raise ValueError('initial_trace_levels 형식을 확인하세요.')
    for key in ('participant_title','participant_description'):
        if key in saved and (not isinstance(saved[key],str) or len(saved[key])>5000):raise ValueError('참가자 과제 설명을 확인하세요.')
    encoded=json.dumps(saved,ensure_ascii=False,allow_nan=False)
    if len(encoded.encode())>3_000_000:raise ValueError('과제 파일은 3 MB 이하이어야 합니다.')
    with catalog_lock:
        folder=directory();folder.mkdir(parents=True,exist_ok=True)
        file=folder/(cid+'.json')
        # Never replace an existing task's code or evaluation data via import.
        with file.open('x',encoding='utf-8') as stream:stream.write(encoded)
    return cid
