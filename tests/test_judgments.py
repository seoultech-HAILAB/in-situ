import json
import uuid

import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend import candidates
from backend.generation import Proposal
from backend.python_runtime import run as native_run


@pytest.fixture
def client(tmp_path,monkeypatch):
    folder=tmp_path/'tasks';folder.mkdir()
    data={'id':'TWO-FAULTS','title':'검수','description':'PRIVATE-DESCRIPTION',
          'input_csv':'qty,price\n2,20\n3,30','target_csv':'qty,price,total\n2,20,40\n3,30,90',
          'initial_code':"s1=input_df.loc[input_df['qty']>2].copy()\nresult=s1.assign(total=s1['qty']*(s1['price']+1))",
          'steps':[{'label':'수량 선택','statement_indices':[0],'output_variable':'s1'},
                   {'label':'금액 계산','statement_indices':[1],'output_variable':'result'}],
          'researcher_notes':{'fault_steps':[1,2]}}
    (folder/'TWO-FAULTS.json').write_text(json.dumps(data),encoding='utf-8')
    store=tmp_path/'sessions';store.mkdir()
    monkeypatch.setattr(server,'STORE',store)
    monkeypatch.setenv('TRACE_TASK_DIR',str(folder));monkeypatch.delenv('TRACE_ACCESS_FILE',raising=False)
    monkeypatch.setattr(server,'isolated_run',lambda code,csv,sources,engine,plan:native_run(code,server.parse_table(csv),{},plan))
    with TestClient(server.app) as client:yield client,data


def start(client,data):
    result=client.post('/api/woz-tasks/TWO-FAULTS/start',json={k:data[k] for k in ('input_csv','target_csv')}).json()
    assert result['status']=='ready'
    return result


def payload(session,indices,answer='steps'):
    baseline=session['review_baseline']
    return {'submission_id':str(uuid.uuid4()),'initial_run_id':baseline['run_id'],
            'execution_version':session['run']['id'],'condition':session['condition'],'answer':answer,
            'step_ids':[baseline['steps'][index-1]['id'] for index in indices]}


def test_multiple_faults_are_scored_as_a_set_without_participant_verdict(client):
    client,data=client;s=start(client,data);url=f"/api/sessions/{s['id']}/initial-step-judgment"
    first=payload(s,[1]);response=client.post(url,json=first)
    assert response.status_code==200 and set(response.json())=={'ok','judgment'}
    assert client.post(url,json=first).json()==response.json()  # Idempotency.
    assert client.post(url,json=payload(s,[1,2])).status_code==200
    assert client.post(url,json=payload(s,[],'uncertain')).status_code==200
    stored=server.read(s['id']);scores=stored['judgment_evaluations']
    assert [item['exact_step_set'] for item in scores]==[False,True,None]
    assert all(item['current_target_match'] is False for item in scores)
    assert len(stored['initial_step_judgments'])==3
    visible=client.get(f"/api/sessions/{s['id']}",headers={'X-Trace-View':'participant'}).json()
    assert 'task_provenance' not in visible and 'judgment_evaluations' not in visible
    assert 'comparison' not in visible['run'] and len(visible['initial_step_judgments'])==3
    assert len([event for event in stored['events'] if event['event']=='initial_step_judgment_submitted'])==3


def test_reject_stale_unknown_duplicate_and_inconsistent_responses(client):
    client,data=client;s=start(client,data);url=f"/api/sessions/{s['id']}/initial-step-judgment"
    valid=payload(s,[1])
    for invalid in [{**valid,'initial_run_id':str(uuid.uuid4())},{**valid,'execution_version':str(uuid.uuid4())},
                    {**valid,'condition':'ex'},{**valid,'step_ids':['invented']},
                    {**valid,'step_ids':valid['step_ids']*2},{**valid,'answer':'none'}]:
        assert client.post(url,json=invalid).status_code==409
    assert server.read(s['id'])['initial_step_judgments']==[]


def test_normal_empty_fault_set_is_a_valid_answer_and_survives_new_step_numbers(client):
    client,data=client
    data['initial_code']="s1=input_df.loc[input_df['qty']>=2].copy()\nresult=s1.assign(total=s1['qty']*s1['price'])"
    data['researcher_notes']['fault_steps']=[]
    (candidates.directory()/'TWO-FAULTS.json').write_text(json.dumps(data),encoding='utf-8')
    s=start(client,data);assert s['run']['comparison']['matches']
    saved=server.read(s['id'])
    # Simulate reordered display numbers: the immutable baseline keeps its IDs.
    saved['runs'][0]['stages'][1]['order']=9;server.save(saved)
    result=client.post(f"/api/sessions/{s['id']}/initial-step-judgment",json=payload(s,[],'none'))
    assert result.status_code==200
    assert server.read(s['id'])['judgment_evaluations'][0]['exact_step_set'] is True


def test_inserted_step_does_not_change_the_initial_answer_identity(client,monkeypatch):
    client,data=client;s=start(client,data);baseline=s['review_baseline']
    class InsertModel:
        def generate(self,inp,target,requirements,previous_code,request,context):
            return Proposal(base_run_id=context['base_run_id'],changes=[{'action':'insert_after',
                'step_id':baseline['steps'][0]['id'],'label':'수량 확인',
                'code':"s1=s1.assign(qty=s1['qty']+0)"}])
    monkeypatch.setattr(server,'generator',InsertModel())
    revised=client.post(f"/api/sessions/{s['id']}/generate",json={'request':'수량을 확인하는 단계 추가',
        'scope':'step','base_run_id':s['run']['id'],'context':{'step_id':baseline['steps'][0]['id']}}).json()
    assert revised['status']=='ready' and len(revised['run']['stages'])==4
    assert revised['review_baseline']==baseline
    assert revised['run']['stages'][3]['id']==baseline['steps'][1]['id']
    result=client.post(f"/api/sessions/{s['id']}/initial-step-judgment",json=payload(revised,[1,2]))
    assert result.status_code==200 and server.read(s['id'])['judgment_evaluations'][0]['exact_step_set'] is True
