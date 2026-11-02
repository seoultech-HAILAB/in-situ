"""Every bundled task must open a complete review without credentials or local state."""
import json
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
import backend.app as server
from backend import candidates,explanations

ROOT=Path(__file__).resolve().parents[1]


def test_empty_existing_install_gets_new_tasks_and_preserves_local_changes(tmp_path,monkeypatch):
    shutil.copytree(ROOT/'tasks',tmp_path/'tasks')
    folder=tmp_path/'.local/pilot/candidates';folder.mkdir(parents=True)
    monkeypatch.setattr(candidates,'ROOT',tmp_path)
    monkeypatch.delenv('TRACE_TASK_DIR',raising=False)
    assert len(candidates.listing())==12
    assert len(candidates.listing(include_disabled=True))==12
    source=tmp_path/'tasks/candidates/VERIFY2-M4-A.json'
    local=folder/source.name
    old=local.read_bytes()
    changed=json.loads(source.read_text(encoding='utf-8-sig'));changed['title']='Updated package'
    source.write_text(json.dumps(changed),encoding='utf-8')
    candidates.directory()
    assert local.read_bytes()!=old
    changed['title']='Local custom title'
    local.write_text(json.dumps(changed),encoding='utf-8')
    changed['title']='Another package update'
    source.write_text(json.dumps(changed),encoding='utf-8')
    candidates.directory()
    assert json.loads(local.read_text(encoding='utf-8'))['title']=='Local custom title'
    local.unlink();candidates.directory()
    assert not local.exists()


def test_all_tasks_execute_describe_switch_and_reopen_without_api_key(tmp_path,monkeypatch):
    shutil.copytree(ROOT/'tasks',tmp_path/'tasks')
    monkeypatch.setattr(candidates,'ROOT',tmp_path)
    monkeypatch.delenv('TRACE_TASK_DIR',raising=False)
    monkeypatch.delenv('TRACE_LEGACY_AUTH',raising=False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setenv('TRACE_EXPLANATION_DIR',str(tmp_path/'no-local-cache'))
    store=tmp_path/'sessions';store.mkdir();monkeypatch.setattr(server,'STORE',store)
    def no_api(*args,**kwargs):raise AssertionError('Initial review must not call a model')
    monkeypatch.setattr(explanations,'generate',no_api)
    with TestClient(server.app) as client:
        tasks=client.get('/api/woz-tasks').json()
        assert len(tasks)==12
        for task in tasks:
            cid=task['id']
            response=client.get(f'/api/woz-tasks/{cid}/input')
            assert response.status_code==200,(cid,response.text)
            data=response.json()
            response=client.post(f'/api/woz-tasks/{cid}/start',json={k:data[k] for k in ('input_csv','target_csv')})
            assert response.status_code==200,(cid,response.text)
            session=response.json();assert session['status']=='ready',(cid,session.get('error'))
            sid=session['id'];rid=session['run']['id']
            response=client.post(f'/api/sessions/{sid}/explanations',json={'run_id':rid})
            assert response.status_code==200,(cid,response.text)
            run=response.json()['run']
            assert run['explanation_status']=='ready',(cid,run.get('explanation_error'))
            for stage in run['stages'][1:]:
                assert stage['nl_explanation']['text'] and 'column_explanations' in stage
                assert all('column_explanations' in op for op in stage.get('operations',[]))
            for condition in ('ex','in-situ'):
                shown=client.post(f'/api/sessions/{sid}/condition',json={'condition':condition},headers={'X-Trace-View':'participant'}).json()['run']
                assert shown['id']==rid and shown['stages']==run['stages']
            assert client.get(f'/api/sessions/{sid}').json()['run']['explanation_status']=='ready'


def test_explanation_key_ignores_library_dtype_labels_but_detects_actual_changes():
    import copy
    from backend.pipeline import prepare,assemble
    from backend.python_runtime import run
    code="result=input_df.assign(total=input_df['qty']*2)"
    plan=prepare(code,engine='python')
    stages,_=assemble(run(code,server.parse_table('qty\n2'),{},plan),plan)
    original={'code':code,'stages':stages};changed=copy.deepcopy(original)
    for stage in changed['stages']:
        for table in [stage.get('input'),stage.get('table')]:
            if table:table['stats']['fields']['dtype-label-test']={'dtype':'str'}
    assert explanations.observation_fingerprint(changed)==explanations.observation_fingerprint(original)
    changed['stages'][1]['table']['rows'][0]['values']['total']=999
    assert explanations.observation_fingerprint(changed)!=explanations.observation_fingerprint(original)
