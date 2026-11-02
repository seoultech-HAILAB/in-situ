import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend import prototype
from backend.generation import OpenAIGenerator,Proposal
from backend.python_runtime import run as native_run


CODE="s1 = input_df.loc[input_df['status']=='done'].copy()\ns2 = s1.assign(amount=s1['quantity']*s1['unit_price'])\nresult = s2.groupby('region',as_index=False).agg(total=('amount','sum'))"
STEPS=[{'label':label,'statement_indices':[i],'output_variable':var} for i,(label,var) in enumerate([
    ('완료 주문 선택','s1'),('매출 계산','s2'),('지역별 집계','result')])]


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    monkeypatch.delenv('TRACE_ACCESS_FILE',raising=False)
    monkeypatch.setattr(server,'isolated_run',lambda code,csv,sources,engine,plan:native_run(code,server.parse_table(csv),{k:server.parse_table(v) for k,v in sources.items()},plan))
    return TestClient(server.app)


def register(client,condition='in-situ'):
    return client.post('/api/prototype/sessions',json={'input_csv':prototype.INPUT,'target_csv':prototype.TARGET,'condition':condition})


def test_table_only_contract_separate_fixture_and_two_conditions(client):
    fixture=client.get('/api/prototype/fixture').json()
    assert fixture['selected_for_study'] is False
    assert 'requirements' not in fixture and 'code' not in fixture
    for condition in ('ex','in-situ'):
        response=register(client,condition);assert response.status_code==200
        session=response.json()
        assert session['requirements']=='' and session['study_mode']==prototype.MODE
        assert session['selected_for_study'] is False and not session['pilot_account']
        assert not session.get('study_task') and session['task_id']=='prototype-check-orders'
        assert session['condition_variant']==prototype.CONDITIONS[condition]
    assert register(client,'B2').status_code==422
    assert client.post('/api/prototype/sessions',json={'input_csv':prototype.INPUT,'target_csv':prototype.TARGET,'requirements':'LEAKED_TASK_DESCRIPTION'}).status_code==422


def test_one_generation_shared_observations_revision_undo_and_failure(client,monkeypatch):
    calls=[]
    class Model:
        def generate(self,inp,target,requirements,previous_code,request,context):
            assert inp==prototype.INPUT and target==prototype.TARGET and requirements==''
            calls.append((previous_code,request,copy.deepcopy(context)))
            if previous_code is None:return Proposal(code=CODE,steps=STEPS)
            assert context['target_step']['table']['columns']==['order_id','region','status','quantity','unit_price']
            return Proposal(base_run_id=context['base_run_id'],changes=[{
                'action':'replace','step_id':context['target_step']['id'],
                'code':context['target_step']['code'].replace("=='done'","!='done'") }])
    monkeypatch.setattr(server,'generator',Model())
    session=register(client).json();sid=session['id']
    assert client.post(f'/api/sessions/{sid}/generate',json={'context':{'task_description':'FORBIDDEN'}}).status_code==422
    first=client.post(f'/api/sessions/{sid}/generate',json={},headers={'X-Trace-View':'participant'}).json()
    assert first['status']=='ready' and first['run']['mode']=='api' and len(calls)==1
    assert 'comparison' not in first['run']
    stages=first['run']['stages'];assert len(stages)==4
    assert [len(stage['table']['rows']) for stage in stages]==[6,4,4,2]
    assert all(stage['inputs'] for stage in stages[1:])
    for condition in ('ex','in-situ','ex'):
        switched=client.post(f'/api/sessions/{sid}/condition',json={'condition':condition},headers={'X-Trace-View':'participant'}).json()
        assert switched['run']==first['run'] and switched['condition_variant']==prototype.CONDITIONS[condition]
    assert len(calls)==1
    assert client.post(f'/api/sessions/{sid}/condition',json={'condition':'B2'}).status_code==422
    revised=client.post(f'/api/sessions/{sid}/generate',json={'request':'완료되지 않은 주문을 사용해 주세요.',
        'scope':'step','base_run_id':first['run']['id'],'context':{'step_id':stages[1]['id']}}).json()
    assert revised['status']=='ready' and len(calls)==2
    assert revised['run']['stages'][1]['id']==stages[1]['id']
    assert revised['run']['stages'][-1]['diff']['output_changed']
    assert not revised['run']['stages'][-1]['diff']['code_changed']
    assert revised['run']['stages'][-1]['diff']['provenance_changed']
    assert revised['run']['stages'][-1]['table']!=stages[-1]['table']
    assert not revised['run']['comparison']['matches']  # User-requested result stays; no Target repair.
    restored=client.post(f'/api/sessions/{sid}/undo',json={}).json()
    assert restored['run']['id']==first['run']['id']
    assert client.post(f'/api/sessions/{sid}/confirm',json={}).json()['confirmed']['run_id']==first['run']['id']
    class Broken:
        def generate(self,*args):return Proposal(code="result=input_df[['not_a_column']]",steps=[{'statement_indices':[0],'output_variable':'result'}])
    monkeypatch.setattr(server,'generator',Broken())
    failed=client.post(f'/api/sessions/{sid}/generate',json={'request':'실패 검증','scope':'pipeline'}).json()
    assert failed['status']=='failed' and failed['run']['id']==first['run']['id']
    assert failed['run'].get('explanation_status')!= 'failed'
    assert client.post(f'/api/sessions/{sid}/confirm',json={}).status_code==422


def test_initial_generation_requires_model_steps(client,monkeypatch):
    class NoSteps:
        def generate(self,*args):return Proposal(code=CODE)
    monkeypatch.setattr(server,'generator',NoSteps())
    sid=register(client).json()['id']
    result=client.post(f'/api/sessions/{sid}/generate',json={}).json()
    assert result['status']=='failed' and result['run'] is None


def test_archived_condition_projects_to_new_ui_without_rewriting_history(client):
    sid=register(client).json()['id']
    saved=server.read(sid)
    server.execute(saved,CODE,[],'research',groups=STEPS)
    saved['condition']='B2';saved['condition_variant']='ex-situ-step-select-v1'
    saved['events'][0].update(condition='B2',condition_variant='ex-situ-step-select-v1')
    server.save(saved);before=server.path(sid).read_bytes()
    visible=client.get(f'/api/sessions/{sid}').json()
    assert visible['condition']=='ex' and visible['legacy_condition']=='B2'
    assert visible['condition_variant']=='ex-situ-review-v2'
    assert visible['run']['id']==saved['runs'][0]['id']
    assert visible['events'][0]['condition']=='B2'
    assert server.path(sid).read_bytes()==before
    for old in ('A','B2','B','C'):
        assert client.post(f'/api/sessions/{sid}/condition',json={'condition':old}).status_code==422


def test_model_generated_dataframe_group_sum_has_verified_contributors():
    from backend.pipeline import prepare,assemble
    code="work = input_df.loc[input_df['status'].eq('done')].copy()\nwork['total'] = work['quantity'] * work['unit_price']\nresult = work.groupby('region',as_index=False,sort=True)['total'].sum()"
    plan=prepare(code,engine='python')
    stages,_=assemble(native_run(code,server.parse_table(prototype.INPUT),{},plan),plan)
    assert stages[-1]['trace_level']=='detailed'
    assert server.compare(stages[-1]['table'],server.table(server.parse_table(prototype.TARGET)))['matches']
    for row in stages[-1]['table']['rows']:
        rid=row['id']
        assert stages[-1]['lineage'][rid]['total']
        assert stages[-1]['lineage'][rid]['region']
        assert stages[-1]['contexts'][rid]['total']['member_rows']


def test_responses_initial_payload_contains_full_tables_without_natural_language_task(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    payloads=[]
    def post(self,url,headers,json):
        payloads.append(json)
        return httpx.Response(200,json={'status':'completed','output':[{'content':[{'type':'output_text','text':__import__('json').dumps({'code':CODE,'steps':[{**step,'id':f'model-step-{i}'} for i,step in enumerate(STEPS)],'changes':[],'assumptions':[],'base_run_id':None})}]}]})
    monkeypatch.setattr(httpx.Client,'post',post)
    proposal=OpenAIGenerator().generate(prototype.INPUT,prototype.TARGET,'')
    actual=json.loads(payloads[0]['input'])
    assert set(actual)=={'input_csv','target_csv'}
    assert actual['input_csv']==prototype.INPUT and actual['target_csv']==prototype.TARGET
    assert proposal.code==CODE and len(proposal.steps)==3 and payloads[0]['store'] is False
    assert all(step.id is None for step in proposal.steps)
