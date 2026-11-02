import json

import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.generation import Proposal
from backend.python_runtime import run as native_run


@pytest.fixture
def client(tmp_path,monkeypatch):
    folder=tmp_path/'tasks';folder.mkdir()
    fixture={'id':'FROZEN','title':'검수 예제','description':'NOT_AN_INITIAL_REQUIREMENT',
             'input_csv':'qty,price\n1,10\n2,20\n3,30',
             'target_csv':'qty,price,total\n2,20,40\n3,30,90',
             'initial_code':"s1 = input_df.loc[input_df['qty'] > 2].copy()\nresult = s1.assign(total=s1['qty']*s1['price'])",
             'steps':[{'statement_indices':[0],'label':'수량 필터','output_variable':'s1'},
                      {'statement_indices':[1],'label':'금액 계산','output_variable':'result'}],
             'participant_enabled':True,
             'provenance':{'initial_origin':'authored_mock','actual_luna_program':False}}
    (folder/'FROZEN.json').write_text(json.dumps(fixture),encoding='utf-8')
    store=tmp_path/'sessions';store.mkdir()
    monkeypatch.setattr(server,'STORE',store)
    monkeypatch.setenv('TRACE_TASK_DIR',str(folder))
    monkeypatch.delenv('TRACE_ACCESS_FILE',raising=False)
    monkeypatch.setattr(server,'isolated_run',lambda code,csv,sources,engine,plan:native_run(code,server.parse_table(csv),{},plan))
    class NoInitialModel:
        def generate(self,*args,**kwargs):raise AssertionError('Initial code must be frozen')
    monkeypatch.setattr(server,'generator',NoInitialModel())
    with TestClient(server.app) as client:yield client


def tables(client):
    data=client.get('/api/woz-tasks/FROZEN/input').json()
    assert 'description' not in data and 'initial_code' not in data
    return {key:data[key] for key in ('input_csv','target_csv')}


def test_frozen_initial_execution_switch_revision_and_undo(client,monkeypatch):
    assert 'description' not in client.get('/api/woz-tasks').json()[0]
    payload=tables(client)
    initial=client.post('/api/woz-tasks/FROZEN/start',json=payload).json()
    assert initial['status']=='ready' and initial['study_mode']=='woz-v1'
    assert initial['requirements']=='' and initial['selected_for_study'] is False
    assert initial['task_provenance']['initial_model_called'] is False
    assert initial['task_provenance']['actual_luna_program'] is False
    assert not initial['run']['comparison']['matches']
    assert [len(step['table']['rows']) for step in initial['run']['stages']]==[3,1,1]
    second=client.post('/api/woz-tasks/FROZEN/start',json={**payload,'condition':'ex'}).json()
    assert second['run']['code']==initial['run']['code']
    assert second['task_provenance']['snapshot_sha256']==initial['task_provenance']['snapshot_sha256']
    sid=initial['id']
    switched=client.post(f'/api/sessions/{sid}/condition',json={'condition':'ex'},headers={'X-Trace-View':'participant'}).json()
    assert switched['run']['id']==initial['run']['id'] and 'comparison' not in switched['run']
    assert client.post(f'/api/sessions/{sid}/generate',json={}).status_code==409
    class RevisionModel:
        def generate(self,inp,target,requirements,previous_code,request,context):
            assert requirements=='' and previous_code==initial['run']['code']
            return Proposal(base_run_id=context['base_run_id'],changes=[{
                'action':'replace','step_id':context['target_step']['id'],
                'code':context['target_step']['code'].replace('> 2','>= 2')}])
    monkeypatch.setattr(server,'generator',RevisionModel())
    step=initial['run']['stages'][1]
    revised=client.post(f'/api/sessions/{sid}/generate',json={'request':'수량 2도 포함',
        'scope':'step','base_run_id':initial['run']['id'],'context':{'step_id':step['id']}}).json()
    assert revised['status']=='ready'
    assert len(revised['run']['stages'][-1]['table']['rows'])==2
    assert revised['run']['stages'][-1]['diff']['output_changed']
    assert revised['run']['stages'][-1]['diff']['provenance_changed']
    assert not revised['run']['stages'][-1]['diff']['code_changed']
    assert client.post(f'/api/sessions/{sid}/undo',json={}).json()['run']['id']==initial['run']['id']


@pytest.mark.parametrize('field',['input_csv','target_csv'])
def test_reject_other_tables_and_require_both(client,field):
    payload=tables(client)
    assert client.post('/api/woz-tasks/FROZEN/start',json={**payload,field:'other\n999'}).status_code==422
    del payload[field]
    assert client.post('/api/woz-tasks/FROZEN/start',json=payload).status_code==422
