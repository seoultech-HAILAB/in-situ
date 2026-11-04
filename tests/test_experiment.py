import importlib.util
import csv
import json
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend import experiment
from backend.share import allowed


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'STORE', tmp_path / 'sessions')
    server.STORE.mkdir()
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('TRACE_LEGACY_AUTH', raising=False)
    client = TestClient(server.app)
    created = client.post('/api/experiments', json={'condition':'in-situ','environment':{'language':'ko'}})
    assert created.status_code == 200, created.text
    state = created.json()
    headers = {'X-Study-Id':state['id'],'X-Study-Token':state['token'], 'X-Trace-View':'participant'}
    base = '/api/experiments/' + state['id']
    return client, base, headers, state, tmp_path


def act(study, action):
    client, base, headers, *_ = study
    result = client.post(base + '/action', headers=headers, json={'action':action})
    assert result.status_code == 200, result.text
    return result.json()


def expire(state):
    current = experiment.load(server, state['id'])
    current['deadline'] = 1
    experiment.save(server, current)


def test_tutorial_is_separate_untimed_and_credential_is_required(study):
    client, base, headers, initial, _ = study
    assert initial['phase'] == 'tutorial' and initial['deadline'] is None
    assert [t['id'] for t in initial['tasks']] == list(experiment.TASKS)
    assert initial['task_order']==['PILOT4-T07','PILOT4-T01','PILOT4-T03']
    assert initial['protocol_version']==initial['current_protocol_version']=='timed-study-v2'
    assert client.get(base).status_code == 403
    state = act(study, 'prepare_tutorial')
    assert state['session_id'] == act(study, 'prepare_tutorial')['session_id']
    session_url = '/api/sessions/' + state['session_id']
    assert client.get(session_url).status_code == 403
    loaded = client.get(session_url, headers=headers).json()
    assert loaded['task_id'] == experiment.TUTORIAL_TASK and len(loaded['run']['stages']) == 5
    tutorial = server.candidates.load(experiment.TUTORIAL_TASK)
    assert loaded['input_csv'] == tutorial['input_csv'] and loaded['sources_csv'] == tutorial['sources']
    assert loaded['run']['code'] == tutorial['initial_code']
    assert len(loaded['run']['stages'][-1]['table']['rows']) == 3
    assert len(loaded['target']['rows']) == 4
    assert '학생 행사 참여 내역 연결' in state['tutorial_task']['title']
    assert 'token_hash' not in client.get(base, headers=headers).text
    assert client.post(session_url + '/condition', headers=headers, json={'condition':'ex'}).status_code == 403


def test_server_deadline_resume_break_and_all_three_tasks(study):
    client, base, headers, *_ = study
    act(study, 'prepare_tutorial')
    for index, task in enumerate(experiment.TASKS):
        state = act(study, 'prepare')
        assert state['phase'] == 'preparing' and state['deadline'] is None
        session_url = '/api/sessions/' + state['session_id']
        assert client.get(session_url, headers=headers).json()['task_id'] == task
        # Loading, explanation preparation and refresh do not start the clock.
        restored = client.get(base, headers=headers).json()
        assert restored['phase'] == 'preparing' and restored['deadline'] is None
        assert client.post(session_url + '/undo', headers=headers, json={}).status_code == 409
        state = act(study, 'begin')
        assert state['phase'] == 'task' and 899 <= state['deadline'] - state['server_now'] <= 900
        assert client.get(base, headers=headers).json()['deadline'] == state['deadline']
        expire(state)
        assert client.post(session_url + '/undo', headers=headers, json={}).status_code == 409
        state = client.get(base, headers=headers).json()
        assert len(state['completed_tasks']) == index + 1
        assert state['completed_tasks'][-1]['reason'] == 'timeout'
        if index < 2:
            assert state['phase'] == 'break'
            # A participant can skip the break while time remains.
            assert state['deadline'] > state['server_now']
            state = act(study, 'next')
            assert state['phase'] == 'ready' and state['task_index'] == index + 1
        else:
            assert state['phase'] == 'complete'
    assert client.post(base + '/action', headers=headers, json={'action':'finish'}).status_code == 409


def test_manual_finish_is_idempotent_with_expected_phase_and_index(study):
    client, base, headers, *_ = study
    state = act(study, 'prepare')
    act(study, 'begin')
    body = {'action':'finish','expected_phase':'task','expected_index':0}
    first = client.post(base+'/action', headers=headers, json=body).json()
    second = client.post(base+'/action', headers=headers, json=body).json()
    assert first['deadline'] == second['deadline']
    assert len(second['completed_tasks']) == 1
    assert second['completed_tasks'][0]['reason'] == 'participant'


def test_events_durable_deduplicated_labelled_and_export_has_no_token(study):
    client, base, headers, state, root = study
    act(study, 'prepare_tutorial')
    entry = {'id':str(uuid.uuid4()),'label':'view.step','client_at':'2026-11-04T01:00:00Z',
             'sequence':1,'page_id':'tab-1','context':{'step_id':'step_2'},'data':{'to':'step_2'}}
    for _ in range(2):
        assert client.post(base+'/events', headers=headers, json={'events':[entry]}).status_code == 200
    with sqlite3.connect(root/'experiments/events.sqlite3') as db:
        rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM events')]
    assert sum(r['id'] == entry['id'] for r in rows) == 1
    row = next(r for r in rows if r['id'] == entry['id'])
    assert row['action_label'] == 'Step 관찰' and row['task_id'] == experiment.TUTORIAL_TASK
    assert row['participant_id'] == state['participant_id'] and row['server_at']
    spec = importlib.util.spec_from_file_location('exporter', server.ROOT/'scripts/export_experiment.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.export(root, root/'export')['sessions'] == 1
    assert state['token'] not in (root/'export/participants.json').read_text(encoding='utf-8')
    assert 'token_hash' not in (root/'export/participants.json').read_text(encoding='utf-8')
    assert 'view.step' in (root/'export/events.jsonl').read_text(encoding='utf-8')


def test_other_participant_cannot_read_session(study):
    client, base, headers, *_ = study
    state = act(study, 'prepare_tutorial')
    other = client.post('/api/experiments', json={'condition':'ex'}).json()
    wrong = {'X-Study-Id':other['id'],'X-Study-Token':other['token']}
    assert client.get('/api/sessions/'+state['session_id'], headers=wrong).status_code == 403
    assert client.get(base, headers=wrong).status_code == 403


def test_public_gateway_rejects_research_and_legacy_endpoints():
    for path in ('/api/pilot/export/json','/api/replay','/api/woz-tasks','/legacy','/docs','/.env',
                 '/api/task-candidates', '/api/sessions/'+str(uuid.uuid4())+'/export'):
        assert not allowed('GET',path) and not allowed('POST',path)
    assert allowed('GET','/in-situ') and allowed('GET','/ex-situ')
    assert allowed('POST','/api/experiments')


def test_new_order_preserves_legacy_task_labels_and_logs(study):
    client,base,headers,initial,root=study
    legacy=experiment.load(server,initial['id'])
    legacy.update(protocol_version='timed-study-v1',phase='ready',task_index=2)
    legacy.pop('task_order')
    experiment.save(server,legacy)
    restored=client.get(base,headers=headers).json()
    assert restored['task_order']==list(experiment.LEGACY_TASKS)
    experiment.record(server,legacy,'study.resumed')
    replacement=client.post('/api/experiments',headers=headers,json={
        'condition':'in-situ','previous_experiment_id':legacy['id']}).json()
    assert replacement['phase']=='tutorial' and replacement['task_order']==list(experiment.TASKS)
    assert replacement['previous_experiment_id']==legacy['id']
    archived=client.get(base,headers=headers).json()
    assert archived['superseded_by']==replacement['id'] and archived['task_order']==list(experiment.LEGACY_TASKS)
    assert client.post(base+'/action',headers=headers,json={'action':'prepare'}).status_code==409
    with sqlite3.connect(root/'experiments/events.sqlite3') as db:
        old=[json.loads(row[0]) for row in db.execute('SELECT payload FROM events WHERE experiment_id=?',(legacy['id'],))]
    resumed=next(row for row in old if row['label']=='study.resumed')
    assert resumed['task_id']=='PILOT4-T05' and resumed['protocol_version']=='timed-study-v1'


def test_old_tutorial_is_replaced_without_removing_its_history(study):
    client, base, headers, initial, _ = study
    registered = server.create(server.Tables(input_csv='x\n1\n', target_csv='x\n1\n', task_id='TUTORIAL'))
    old = server.read(registered['id'])
    server.execute(old, 'result = input_df.copy()', [], 'research')
    old.update(experiment_id=initial['id'], participant_id=initial['participant_id'])
    server.save(old)
    state = experiment.load(server, initial['id'])
    state.update(session_id=old['id'], tutorial_session_id=old['id'])
    experiment.save(server, state)
    restored = act(study, 'prepare_tutorial')
    assert restored['session_id'] != old['id']
    assert restored['previous_tutorial_session_ids'] == [old['id']]
    previous = client.get('/api/sessions/'+old['id'], headers=headers).json()
    assert previous['run']['code'] == old['runs'][0]['code']
    assert act(study, 'prepare_tutorial')['session_id'] == restored['session_id']


def test_approval_finishing_after_deadline_never_commits(study, monkeypatch):
    from backend.generation import Proposal
    client, _, headers, *_ = study
    state = act(study, 'prepare_tutorial')
    state = act(study, 'prepare')
    state = act(study, 'begin')
    session_url = '/api/sessions/' + state['session_id']
    baseline = client.get(session_url, headers=headers).json()['run']
    target = baseline['pipeline']['steps'][0]

    class Generator:
        def generate(self, *args):
            return Proposal(base_run_id=baseline['id'], revision_scope='step', changes=[{
                'action':'replace','step_id':target['id'],'code':target['code'],
            }])

    monkeypatch.setattr(server, 'generator', Generator())
    response = client.post(session_url+'/revision-preview', headers=headers, json={
        'request':'현재 계산을 유지해줘','base_run_id':baseline['id'],'context':{'step_id':target['id']},
    })
    assert response.status_code == 200, response.text
    preview = response.json()['pending_revision']
    assert preview['status'] == 'ready'
    original_execute = server.execute

    def expires_during_execution(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        expire(state)
        return result

    monkeypatch.setattr(server, 'execute', expires_during_execution)
    response = client.post(session_url+'/revision-preview/'+preview['id']+'/approve', headers=headers, json={})
    assert response.status_code == 409
    assert client.get(session_url, headers=headers).json()['run']['id'] == baseline['id']


def test_event_export_includes_real_start_end_and_korean_local_time(study):
    _, _, _, _, root=study
    act(study,'prepare');started=act(study,'begin');act(study,'finish')
    state=experiment.load(server,started['id'])
    assert state['completed_tasks'][0]['started_at']==started['started_at']
    assert started['deadline']-started['started_at']==900
    spec=importlib.util.spec_from_file_location('timestamp_export',server.ROOT/'scripts/export_experiment.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.export(root,root/'timestamp-export')
    with (root/'timestamp-export/events.csv').open(encoding='utf-8-sig',newline='') as file:rows=list(csv.DictReader(file))
    begin=next(row for row in rows if row['label']=='task.started')
    end=next(row for row in rows if row['label']=='task.finished')
    assert begin['server_at'] and begin['server_at_kst'].endswith('+09:00')
    assert begin['task_started_at_utc'].endswith('+00:00')
    assert end['task_started_at_kst']==begin['task_started_at_kst']
    assert end['task_ended_at_kst'] and end['task_ended_at_utc']
    assert module.display_time(0,True)=='1970-01-01T09:00:00.000+09:00'
