import copy
import json
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend import explanations
from backend.pipeline import prepare,assemble
from backend.python_runtime import run as native_run


def snapshot():
    code="result = input_df.assign(total=input_df['qty']*2)"
    frame=server.parse_table('qty,note\n2,PRIVATE_INPUT_VALUE')
    plan=prepare(code,engine='python');stages,_=assemble(native_run(code,frame,{},plan),plan)
    return {'id':str(uuid4()),'code_version':1,'code':code,'stages':stages,'pipeline':plan}


def bundle(run):
    return {'fingerprint':explanations.fingerprint(run),'model':explanations.model(),'prompt_version':explanations.PROMPT_VERSION,
            'steps':[{'step_no':1,'title':'수량의 두 배 계산','text':'각 행의 수량을 두 배로 계산해 total 열에 저장합니다.'}],
            'columns':[{k:v for k,v in target.items() if k in ('step_no','operation_no','column')}|{'text':'수량의 두 배 계산'} for target in explanations.column_targets(run)],
            'transformations':[{k:target[k] for k in ('step_no','transformation_no')}|{'text':'수량에 2를 곱해 계산합니다.'} for target in explanations.transformation_targets(run)]}


def test_real_api_contract_observed_diff_cache_ignores_runtime_ids_and_detects_changed_data(monkeypatch,tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY','test-api-key');monkeypatch.setenv('OPENAI_MODEL','test-model')
    monkeypatch.setenv('TRACE_EXPLANATION_DIR',str(tmp_path))
    calls=[];run=snapshot()
    def post(self,url,headers,json):
        calls.append(json)
        assert url.endswith('/responses') and json['store'] is False
        assert 'PRIVATE_INPUT_VALUE' not in json['input']
        payload=__import__('json').loads(json['input'])
        assert set(payload)=={'code','steps','column_targets','transformation_targets','observed_changes'} and set(payload['steps'][0])=={'step_no','code','upstream_steps'}
        observed=payload['observed_changes'][0]
        assert observed['after']['sample'][0]['values']['total']==4
        assert observed['changes'][0]['column']=='total'
        assert payload['column_targets'] and all(set(t)=={'step_no','operation_no','column','code','expression'} for t in payload['column_targets'])
        assert payload['code']==run['code']
        data={k:bundle(run)[k] for k in ('steps','columns','transformations')}
        data['change_links']=[{'step_no':item['step_no'],'change_id':event['id'],'status':'linked',
            'operations':[{'candidate_id':event['candidate_ids'][0],'text':'수량에 2를 곱해 total 열을 만듭니다.'}]}
            for item in payload['observed_changes'] for event in item['changes']]
        return httpx.Response(200,json={'status':'completed','id':'test-response','usage':{'total_tokens':123},
            'output':[{'content':[{'type':'output_text','text':__import__('json').dumps(data)}]}]})
    monkeypatch.setattr(httpx.Client,'post',post)
    a,cached=explanations.obtain(run);assert not cached
    other=copy.deepcopy(run);other['id']=str(uuid4());other['stages'][1]['id']=str(uuid4())
    b,cached=explanations.obtain(other);assert cached and a==b and len(calls)==1
    assert a['usage']['total_tokens']==123
    other['stages'][1]['table']['rows'][0]['values']['total']=9
    assert explanations.fingerprint(other)!=explanations.fingerprint(run)
    with pytest.raises(ValueError):explanations.attach(other,a,True)


def session(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    s=server.create(server.Tables(input_csv='qty\n2',target_csv='total\n99',condition='A'))
    s.pop('run',None);r=snapshot();s.update(runs=[r],cursor=0,status='ready');server.save(s)
    return s,r,TestClient(server.app)


def test_explanation_api_is_version_bound_and_never_changes_execution(tmp_path,monkeypatch):
    s,r,client=session(tmp_path,monkeypatch)
    monkeypatch.setattr(explanations,'obtain',lambda current:(bundle(current),False))
    response=client.post(f"/api/sessions/{s['id']}/explanations",json={'run_id':r['id']})
    assert response.status_code==200
    data=response.json();assert data['status']=='ready' and data['run']['id']==r['id'] and data['run']['code']==r['code']
    assert data['run']['stages'][1]['table']==r['stages'][1]['table']
    assert data['run']['stages'][1]['nl_explanation']['text']=='각 행의 수량을 두 배로 계산해 total 열에 저장합니다.'
    assert data['run']['stages'][1]['column_explanations']['total']=='수량의 두 배 계산'
    assert data['run']['stages'][1]['operations'][0]['column_explanations']['total']=='수량의 두 배 계산'
    assert data['run']['explanation_meta']['source']=='llm'
    assert client.post(f"/api/sessions/{s['id']}/explanations",json={'run_id':str(uuid4())}).status_code==409


def test_explanation_failure_is_separate_from_execution_failure(tmp_path,monkeypatch):
    s,r,client=session(tmp_path,monkeypatch)
    def fail(_):raise ValueError('test API unavailable')
    monkeypatch.setattr(explanations,'obtain',fail)
    data=client.post(f"/api/sessions/{s['id']}/explanations",json={'run_id':r['id']}).json()
    assert data['status']=='ready' and data['run']['id']==r['id'] and data['error'] is None
    assert data['run']['explanation_status']=='failed'
    assert 'nl_explanation' not in data['run']['stages'][1]


def test_concurrent_revision_cannot_receive_an_old_explanation(tmp_path,monkeypatch):
    s,r,client=session(tmp_path,monkeypatch)
    def change(current):
        changed=server.read(s['id']);new=copy.deepcopy(r);new['id']=str(uuid4());new['code_version']=2
        changed['runs'].append(new);changed['cursor']=1;server.save(changed)
        return bundle(current),False
    monkeypatch.setattr(explanations,'obtain',change)
    assert client.post(f"/api/sessions/{s['id']}/explanations",json={'run_id':r['id']}).status_code==409
    assert 'nl_explanation' not in server.read(s['id'])['runs'][-1]['stages'][1]


def test_model_must_return_prose_for_every_real_step():
    with pytest.raises(ValueError):explanations.validate_steps({'steps':[{'step_no':2,'title':'설명','text':'값을 계산합니다.'}]},1)
    with pytest.raises(ValueError):explanations.validate_steps({'steps':[{'step_no':1,'title':'설명','text':'astype(str)을 적용합니다.'}]},1)


def test_column_explanations_require_exact_operation_column_and_natural_language():
    run=snapshot();data=bundle(run)
    explanations.validate_steps(data,1,run)
    wrong=copy.deepcopy(data);wrong['columns'][0]['column']='unobserved'
    with pytest.raises(ValueError):explanations.validate_steps(wrong,1,run)
    missing=copy.deepcopy(data);missing['columns'].pop()
    with pytest.raises(ValueError):explanations.validate_steps(missing,1,run)
    code=copy.deepcopy(data);code['columns'][0]['text']="STRIP(ASTYPE(total, <class 'str'>))"
    with pytest.raises(ValueError):explanations.validate_steps(code,1,run)


def test_c_explanations_attach_to_current_run_and_do_not_survive_a_changed_formula(tmp_path,monkeypatch):
    s,r,client=session(tmp_path,monkeypatch);s['condition']='C';server.save(s)
    monkeypatch.setattr(explanations,'obtain',lambda current:(bundle(current),False))
    result=client.post(f"/api/sessions/{s['id']}/explanations",json={'run_id':r['id']}).json()
    assert result['condition']=='in-situ'
    assert result['run']['stages'][1]['column_explanations']['total']=='수량의 두 배 계산'
    changed=copy.deepcopy(r);changed['stages'][1]['params']['formulas']['total']['formula']='qty * 3'
    with pytest.raises(ValueError):explanations.attach(changed,bundle(r),False)


def test_explicit_refresh_upgrades_legacy_explanations_without_reexecuting_code(tmp_path,monkeypatch):
    s,r,client=session(tmp_path,monkeypatch)
    calls=[]
    def obtain(current,require_transformations=False):
        calls.append(require_transformations)
        result=bundle(current)
        if not require_transformations:result.pop('transformations')
        return result,False
    monkeypatch.setattr(explanations,'obtain',obtain)
    old=client.post(f"/api/sessions/{s['id']}/explanations",json={'run_id':r['id']}).json()['run']
    assert old['stages'][1]['transformations'][0]['description']['source']=='ast'
    fresh=client.post(f"/api/sessions/{s['id']}/explanations",json={'run_id':r['id'],'refresh_transformations':True}).json()['run']
    assert fresh['stages'][1]['transformations'][0]['description']['source']=='llm'
    assert fresh['id']==old['id'] and fresh['code']==old['code'] and fresh['stages'][1]['table']==old['stages'][1]['table']
    assert calls==[False,True]
