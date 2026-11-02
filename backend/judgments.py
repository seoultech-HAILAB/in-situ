"""Initial Step-set self reports; scoring is researcher-only and never corrective."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,Field


class Judgment(BaseModel):
    model_config={'extra':'forbid'}
    submission_id:UUID
    initial_run_id:UUID
    execution_version:UUID
    condition:Literal['ex','in-situ']
    answer:Literal['steps','none','uncertain']
    step_ids:list[str]=Field(default_factory=list,max_length=40)


def initialize(session,run,fault_steps=None):
    steps=[{'id':step['id'],'order':index,'label':step.get('intent_label') or step['label']}
           for index,step in enumerate(run['stages'][1:],1)]
    session['review_baseline']={'run_id':run['id'],'code_version':run['code_version'],'steps':steps}
    if fault_steps is not None:
        if any(type(index) is not int or not 1<=index<=len(steps) for index in fault_steps):
            raise ValueError('초기 오류 Step 정답 위치가 유효하지 않습니다.')
        session['task_provenance']['initial_fault_step_ids']=[steps[index-1]['id'] for index in fault_steps]
    session['initial_step_judgments']=[]
    session['judgment_evaluations']=[]


def evaluate(session,payload,current_run):
    baseline=session.get('review_baseline')
    if not baseline or payload['initial_run_id']!=baseline['run_id']:
        raise ValueError('초기 실행 기준이 다릅니다.')
    if payload['execution_version']!=current_run['id'] or payload['condition']!=session['condition']:
        raise ValueError('실행 버전이나 조건이 바뀌었습니다. 다시 열어주세요.')
    chosen=payload['step_ids'];known={step['id'] for step in baseline['steps']}
    if len(chosen)!=len(set(chosen)) or any(step not in known for step in chosen):
        raise ValueError('초기 실행에 존재하는 Step을 중복 없이 선택하세요.')
    if bool(chosen)!=(payload['answer']=='steps'):
        raise ValueError('Step 선택과 응답 유형이 일치하지 않습니다.')
    expected=session.get('task_provenance',{}).get('initial_fault_step_ids')
    scored=expected is not None and payload['answer']!='uncertain'
    picked=set(chosen);truth=set(expected or [])
    return {'submission_id':payload['submission_id'],'initial_run_id':baseline['run_id'],
            'execution_version':current_run['id'],'scored':scored,
            'exact_step_set':picked==truth if scored else None,
            'expected_step_ids':expected,
            'missed_step_ids':sorted(truth-picked) if scored else None,
            'extra_step_ids':sorted(picked-truth) if scored else None,
            'current_target_match':current_run.get('comparison',{}).get('matches')}
