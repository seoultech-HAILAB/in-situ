import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.access import password_hash


@pytest.fixture
def pilot(tmp_path,monkeypatch):
    cfg={'signing_key':'pilot-test-key-'*4,'users':{
        'team':{'role':'researcher','password_hash':password_hash('admin-test')},
        **{pid:{'role':'participant','pilot':True,'participant_id':pid,'password_hash':password_hash('member-test')}
           for pid in ('P01','P02')}},'allowed_origins':[]}
    file=tmp_path/'access.json';file.write_text(json.dumps(cfg),encoding='utf-8')
    monkeypatch.setenv('TRACE_LEGACY_AUTH','1')
    monkeypatch.setenv('TRACE_ACCESS_FILE',str(file))
    store=tmp_path/'sessions';store.mkdir();monkeypatch.setattr(server,'STORE',store)
    task_dir=tmp_path/'tasks';task_dir.mkdir();monkeypatch.setenv('TRACE_TASK_DIR',str(task_dir))
    for number in range(1,17):
        cid=f'R500-{number:03}'
        (task_dir/(cid+'.json')).write_text(json.dumps({'id':cid,'review_number':number,'title':'시험 과제','description':'입력을 출력하세요.',
            'input_csv':'a\n1','target_csv':'a\n1','initial_code':'result = input_df.copy()',
            'steps':[{'statement_indices':[0],'output_variable':'result'}],'enabled':True,'participant_enabled':True}),encoding='utf-8')
    from backend.python_runtime import run as native_run
    monkeypatch.setattr(server,'isolated_run',lambda code,csv,sources,engine,plan:native_run(code,server.parse_table(csv),{k:server.parse_table(v) for k,v in sources.items()},plan))
    clients={}
    for name in cfg['users']:
        client=TestClient(server.app,base_url='https://pilot.example.test')
        assert client.post('/auth/login',data={'username':name,'password':'admin-test' if name=='team' else 'member-test'},follow_redirects=False).status_code==303
        clients[name]=client
    return clients,store,file


def create(client,condition='C'):
    r=client.post('/api/pilot-assignment/start',json={'condition':condition,'participant_id':'spoofed'})
    assert r.status_code==200
    return r.json()


def test_independent_identity_and_session_access_under_concurrency(pilot):
    clients,_,_=pilot
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=list(pool.map(create,[clients['P01'],clients['P02']]))
    for session,pid,other in ((a,'P01','P02'),(b,'P02','P01')):
        assert session['participant_id']==pid and session['pilot_account']
        assert all(e['participant_id']==pid and e['actor_id']==pid for e in server.read(session['id'])['events'])
        assert clients[other].get(f"/api/sessions/{session['id']}").status_code==404
        assert clients[other].post(f"/api/sessions/{session['id']}/undo",json={}).status_code==404
        mine=clients[pid].get('/api/my-sessions').json()
        assert [s['session_id'] for s in mine['sessions']]==[session['id']]
    assert server.request_identity.get() is None
    for route in ('/api/pilot/summary','/api/pilot/export/events.jsonl','/api/task-candidates'):
        assert clients['P01'].get(route,headers={'X-Trace-View':'researcher'}).status_code==403
    health=clients['P01'].get('/api/health').json()
    assert health['participant_id']=='P01' and health['pilot_account'] and health['access_role']=='participant'


def test_feedback_bound_to_identity_version_and_idempotent(pilot):
    clients,_,_=pilot
    s=create(clients['P01'])
    body={'submission_id':str(uuid4()),'condition':s['condition'],'execution_version':s['run']['id'],
          'task_clarity':5,'navigation_ease':3,'change_understanding':None,'outcome':'uncertain','comments':'Step 2 question',
          'participant_id':'P02'}
    url=f"/api/sessions/{s['id']}/feedback"
    for _ in range(2):assert clients['P01'].post(url,json=body).status_code==200
    stored=server.read(s['id'])
    assert len(stored['feedbacks'])==1
    assert stored['feedbacks'][0]['participant_id']=='P01' and stored['feedbacks'][0]['actor_id']=='P01'
    assert clients['P01'].post(url,json={**body,'comments':'different'}).status_code==409
    assert clients['P01'].post(url,json={**body,'submission_id':str(uuid4()),'execution_version':str(uuid4())}).status_code==409
    assert clients['P01'].post(url,json={**body,'submission_id':str(uuid4()),'condition':'C'}).status_code==409
    assert clients['P01'].post(url,json={**body,'task_clarity':6}).status_code==422
    assert clients['P02'].post(url,json=body).status_code==404


def test_selected_log_removal_is_private_recoverable_and_rejects_new_activity(pilot):
    clients,store,cfg=pilot
    a=create(clients['P01']);b=create(clients['P02'])
    original_config=cfg.read_bytes()
    admin=clients['team']
    summary=admin.get('/api/pilot/summary').json()['sessions']
    row=next(r for r in summary if r['session_id']==a['id'])
    body={'sessions':[{'session_id':a['id'],'last_event_id':row['last_event_id']}]}
    assert clients['P01'].post('/api/pilot/discard',json=body).status_code==403
    assert clients['P01'].post(f"/api/sessions/{a['id']}/events",json={'event':'step_selected','data':{}}).status_code==200
    assert admin.post('/api/pilot/discard',json=body).status_code==409
    row=next(r for r in admin.get('/api/pilot/summary').json()['sessions'] if r['session_id']==a['id'])
    body['sessions'][0]['last_event_id']=row['last_event_id']
    result=admin.post('/api/pilot/discard',json=body)
    assert result.status_code==200
    assert not (store/f"{a['id']}.json").exists() and (store/f"{b['id']}.json").exists()
    assert (store.parent/'deleted_sessions'/result.json()['recovery_batch']/f"{a['id']}.json").exists()
    assert cfg.read_bytes()==original_config
    assert clients['P01'].get(f"/api/sessions/{a['id']}").status_code==404
    assert 'P02' in admin.get('/api/pilot/export/sessions.csv').text
    events=[json.loads(line) for line in admin.get('/api/pilot/export/events.jsonl').text.splitlines()]
    assert events and all(e['participant_id']=='P02' for e in events)


def test_setup_and_compatibility_provision_create_no_credentials(tmp_path,monkeypatch):
    import scripts.setup_team as setup_module
    import scripts.provision_pilot_members as provisioner
    monkeypatch.setattr(setup_module,'ROOT',tmp_path)
    monkeypatch.setattr(provisioner,'setup',setup_module.setup)
    folder=setup_module.setup()
    provisioner.provision()
    assert folder==tmp_path/'.local/pilot'
    assert (folder/'sessions').is_dir()
    assert sorted(p.name for p in folder.iterdir())==['sessions']


def test_fixed_balancing_cannot_choose_skip_or_duplicate(pilot):
    from backend.pilot_plan import allocations,TASK_NUMBERS
    clients,_,_=pilot
    for task in (f'R500-{number:03}' for number in TASK_NUMBERS):
        assert {next(a['condition'] for a in allocations(pid) if a['task_id']==task) for pid in ('P01','P02','P03')}=={'ex','in-situ'}
    for pid in ('P01','P02','P03'):
        plan=allocations(pid)
        assert len(plan)==len({a['task_id'] for a in plan})
        assert {a['condition'] for a in plan[:3]}=={'ex','in-situ'}
    client=clients['P01']
    assert client.post('/api/sessions',json={'input_csv':'a\n1','target_csv':'a\n1'}).status_code==403
    assert client.post('/api/study-tasks/R500-001/start',json={'condition':'C'}).status_code==403
    assert client.get('/api/study-tasks/R500-002/input').status_code==403
    first=create(client)
    assert first['condition']=='ex' and first['task_id']=='R500-001'
    assert create(client)['id']==first['id']
    state=client.get('/api/pilot-assignment').json()
    assert state['current']['order']==1 and state['session_id']==first['id']
    assert [a['status'] for a in state['assignments']]==['current']+['locked']*12
    assert client.post(f"/api/sessions/{first['id']}/feedback",json={'submission_id':str(uuid4()),'condition':'ex',
        'execution_version':first['run']['id'],'outcome':'uncertain'}).status_code==200
    state=client.get('/api/pilot-assignment').json()
    assert state['completed']==1 and state['assignments'][0]['status']=='completed' and state['assignments'][1]['status']=='current'
    assert client.get('/api/study-tasks/R500-001/input').status_code==403
    second=create(client)
    assert second['id']!=first['id'] and second['task_id']=='R500-002' and second['condition']=='in-situ'


def test_archived_three_condition_completions_do_not_complete_new_condition_trials():
    from backend.pilot_plan import allocations,progress
    assert [len(allocations(pid)) for pid in ('P01','P02','P03')]==[13,13,13]
    assert all(a['review_number'] not in (5,6,12) for pid in ('P01','P02','P03') for a in allocations(pid))
    old=[]
    for position,number in enumerate((1,2,6,3,4,5,7),1):
        old.append({'id':str(uuid4()),'participant_id':'P01','task_id':f'R500-{number:03}',
                    'condition':['A','B2','C'][position-1] if position<=3 else 'C',
                    'created_at':str(position),'feedbacks':[{}] if number!=7 else [],
                    'assignment':{'id':f'pilot-balanced-v1:P01:{position:02}','plan_version':'pilot-balanced-v1'}})
    state=progress('P01',old)
    assert state['completed']==0 and state['current']['review_number']==1
    assert state['current']['condition']=='ex' and state['session_id'] is None
    assert state['assignments'][0]['status']=='current'


def test_every_task_has_all_conditions_and_task_order_rotates():
    from collections import Counter
    from backend.pilot_plan import allocations,TASK_NUMBERS,VERSION
    plans=[allocations(pid) for pid in ('P01','P02','P03')]
    assert len({tuple(item['task_id'] for item in plan) for plan in plans})==3
    for plan in plans:
        assert {item['review_number'] for item in plan}==set(TASK_NUMBERS)
        counts=Counter(item['condition'] for item in plan)
        assert max(counts.values())-min(counts.values())==1
        assert all(item['plan_version']==VERSION for item in plan)
    assert Counter(item['condition'] for plan in plans for item in plan)=={'ex':20,'in-situ':19}


def test_excluded_task_is_unpublished_and_cannot_be_started_or_republished(pilot):
    clients,_,_=pilot
    admin=clients['team']
    assert all(item['id']!='R500-006' for item in admin.get('/api/study-tasks').json())
    assert admin.get('/api/study-tasks/R500-006/input').status_code==404
    assert admin.post('/api/study-tasks/R500-006/start',json={'condition':'C'}).status_code==422
    assert admin.post('/api/task-candidates/R500-006/publication',json={'visible':True}).status_code==422


@pytest.mark.parametrize('outcome',['task_issue','time_limit'])
def test_task_problem_feedback_is_recorded_without_grading_and_unlocks_next_task(pilot,outcome):
    clients,_,_=pilot;client=clients['P01'];s=create(client)
    payload={'submission_id':str(uuid4()),'condition':s['condition'],'execution_version':s['run']['id'],
             'outcome':outcome,'issue_types':['insufficient_input','target_inconsistent'],
             'comments':'입력의 식별 정보로는 Target의 근거를 판단하기 어려움'}
    response=client.post(f"/api/sessions/{s['id']}/feedback",json=payload)
    assert response.status_code==200
    assert response.json()['feedback']['issue_types']==payload['issue_types']
    stored=server.read(s['id'])
    assert stored['confirmed'] is None and stored['target']==s['target']
    assert client.get('/api/pilot-assignment').json()['current']['review_number']==2
    exported=clients['team'].get('/api/pilot/export/feedback.csv').text
    assert 'issue_types' in exported and 'insufficient_input' in exported


def test_target_visible_in_task_input_and_existing_session_without_grading(pilot):
    clients,_,_=pilot
    for pid in ('P01','P02'):
        client=clients[pid]
        task=client.get('/api/pilot-assignment/input').json()
        assert task['target']['columns']==['a'] and task['target_csv']=='a\n1'
        s=create(client)
        assert s['target']==task['target'] and s['target_csv']==task['target_csv']
        assert 'comparison' not in s['run'] and 'task_provenance' not in s
        old=server.read(s['id']);old['study_task']['target_visibility']='researcher';server.save(old)
        restored=client.get(f"/api/sessions/{s['id']}").json()
        assert restored['target']==task['target'] and restored['study_task']['target_visibility']=='participant'
        assert 'comparison' not in restored['run']
