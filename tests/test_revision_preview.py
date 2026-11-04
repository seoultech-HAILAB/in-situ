import copy
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.generation import Proposal
from backend import explanations


CODE = "first = input_df.copy()\nsecond = first.assign(y=first['x'] * 2)\nresult = second[['y']]"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'STORE', tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    session = server.create(server.Tables(input_csv='x\n1\n2', target_csv='y\n3\n6', execution_engine='python'))
    session.pop('run', None)
    server.execute(session, CODE, [], 'research')
    server.save(session)
    base = copy.deepcopy(server.current(session))
    target = base['stages'][2]['id']
    calls = []

    class Generator:
        changes = None
        scope = None
        assumptions = []

        def generate(self, *args):
            calls.append(args[-1])
            return Proposal(base_run_id=base['id'], revision_scope=self.scope, assumptions=self.assumptions,
                            changes=self.changes or [{'action': 'replace', 'step_id': target,
                                                      'code': "second = first.assign(y=first['x'] * 3)"}])

    generator = Generator()
    monkeypatch.setattr(server, 'generator', generator)
    client = TestClient(server.app)
    url = f"/api/sessions/{session['id']}"
    body = {'request': 'y를 세 배로 계산해줘', 'base_run_id': base['id'], 'context': {'step_id': target}}
    return client, url, body, base, generator, calls


def propose(workspace):
    client, url, body, *_ = workspace
    response = client.post(url + '/revision-preview', json=body)
    assert response.status_code == 200, response.text
    session = response.json()
    assert session['pending_revision']['status'] == 'ready', session['pending_revision']
    return session, url + '/revision-preview/' + session['pending_revision']['id']


def test_preview_preserves_confirmed_run_and_exposes_only_selected_step(workspace):
    client, url, _, base, _, calls = workspace
    session, _ = propose(workspace)
    preview = session['pending_revision']
    assert session['run']['id'] == base['id'] and len(session['runs']) == 1
    assert session['run']['code'] == CODE
    assert preview['label'] == 'Step 2a'
    assert preview['step_id'] == base['stages'][2]['id']
    assert preview['stage']['table']['rows'][0]['values']['y'] == 3
    assert session['run']['stages'][2]['table']['rows'][0]['values']['y'] == 2
    assert set(preview).isdisjoint({'plan', 'preview_run', 'runs', 'stages', 'code'})
    assert 'result =' not in preview['step_code']
    assert calls[0]['scope'] == 'auto' and calls[0]['target_step']['id'] == preview['step_id']
    assert client.get(url + '/output.csv').text.lstrip('\ufeff').strip() == 'y\r\n2\r\n4'
    assert client.get(url).json()['pending_revision'] == preview


def test_deny_discards_preview_without_changing_code_results_or_history(workspace):
    client, url, *_ = workspace
    original = client.get(url).json()
    _, decision = propose(workspace)
    denied = client.post(decision + '/deny').json()
    assert denied['pending_revision'] is None
    assert denied['run'] == original['run'] and denied['runs'] == original['runs']
    assert client.post(decision + '/approve').status_code == 409


def test_approve_executes_and_commits_complete_pipeline_only_once(workspace):
    client, _, _, base, *_ = workspace
    _, decision = propose(workspace)
    approved = client.post(decision + '/approve').json()
    assert approved['pending_revision'] is None and len(approved['runs']) == 2
    assert approved['runs'][0]['id'] == base['id']
    assert approved['run']['id'] != base['id'] and approved['run']['parent_run_id'] == base['id']
    assert approved['run']['stages'][-1]['table']['rows'][0]['values']['y'] == 3
    assert len(approved['run']['stages']) == 4
    assert client.post(decision + '/approve').status_code == 409


def test_downstream_is_not_run_until_approval_and_failure_is_atomic(workspace):
    client, _, _, base, generator, *_ = workspace
    generator.changes = [{'action': 'replace', 'step_id': base['stages'][2]['id'], 'code': "second = first.assign(z=first['x'] * 3).drop(columns=['x'])"}]
    session, decision = propose(workspace)
    assert session['pending_revision']['stage']['table']['columns'] == ['z']
    approved = client.post(decision + '/approve').json()
    assert approved['run']['id'] == base['id'] and len(approved['runs']) == 1
    assert approved['pending_revision']['status'] == 'ready'
    assert not approved.get('revision_history')
    assert '전체 파이프라인 실행 실패' in approved['pending_revision']['error']
    denied = client.post(decision + '/deny').json()
    assert denied['run']['id'] == base['id'] and denied['pending_revision'] is None


def test_global_intent_still_previews_only_target_and_commits_other_steps_on_approval(workspace):
    client, _, _, base, generator, *_ = workspace
    generator.scope = 'pipeline'
    generator.changes = [
        {'action': 'replace', 'step_id': base['stages'][1]['id'], 'code': "first = input_df.assign(x=input_df['x'] + 10)"},
        {'action': 'replace', 'step_id': base['stages'][2]['id'], 'code': "second = first.assign(y=first['x'] * 3)"},
        {'action': 'replace', 'step_id': base['stages'][3]['id'], 'code': "result = second[['x', 'y']]"},
    ]
    session, decision = propose(workspace)
    assert session['pending_revision']['scope'] == 'pipeline'
    assert session['pending_revision']['stage']['table']['rows'][0]['values']['y'] == 33
    assert session['run']['stages'][-1]['table']['columns'] == ['y']
    assert 'result =' not in session['pending_revision']['step_code']
    approved = client.post(decision + '/approve').json()
    assert approved['run']['stages'][-1]['table']['columns'] == ['x', 'y']


def test_rejects_stale_versions_parallel_writes_and_invalid_target(workspace):
    client, url, body, *_ = workspace
    assert client.post(url + '/revision-preview', json={**body, 'base_run_id': 'old'}).status_code == 409
    assert client.post(url + '/revision-preview', json={**body, 'context': {}}).status_code == 422
    propose(workspace)
    assert client.post(url + '/revision-preview', json=body).status_code == 409
    assert client.post(url + '/generate', json={'request': 'edit'}).status_code == 409
    assert client.post(url + '/undo').status_code == 409
    assert client.post(url + '/research-code', json={'code': CODE}).status_code == 409


def test_failed_candidate_remains_discardable_and_does_not_replace_baseline(workspace):
    client, url, body, base, generator, *_ = workspace
    generator.changes = [{'action': 'replace', 'step_id': base['stages'][2]['id'], 'code': "second = first[['missing']]"}]
    session = client.post(url + '/revision-preview', json=body).json()
    preview = session['pending_revision']
    assert preview['status'] == 'failed' and 'stage' not in preview
    assert session['run']['id'] == base['id'] and session['status'] == 'ready'
    assert client.post(url + f"/revision-preview/{preview['id']}/approve").status_code == 409
    assert client.post(url + f"/revision-preview/{preview['id']}/deny").json()['pending_revision'] is None


def test_slow_generation_does_not_lock_observation(workspace, monkeypatch):
    client, url, body, base, generator, *_ = workspace
    entered, release = threading.Event(), threading.Event()
    original = generator.generate

    def slow(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(generator, 'generate', slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(client.post, url + '/revision-preview', json=body)
        assert entered.wait(3)
        try:
            observed = pool.submit(client.get, url).result(timeout=2).json()
            assert observed['run']['id'] == base['id']
            assert observed['pending_revision']['status'] == 'generating'
        finally:
            release.set()
        assert future.result(timeout=8).json()['pending_revision']['status'] == 'ready'


def test_candidate_explanations_are_one_version_bound_snapshot_for_both_conditions(workspace, monkeypatch):
    client, url, _, base, *_ = workspace
    _, decision = propose(workspace)

    def obtain(run, **kwargs):
        return {'fingerprint': explanations.fingerprint(run), 'model': 'test', 'prompt_version': explanations.PROMPT_VERSION,
                'steps': [{'step_no': 1, 'title': '세 배 계산', 'text': '원본 x 값에 3을 곱해 y 열을 만듭니다.'}],
                'columns': [{**{k: target[k] for k in ('step_no', 'operation_no', 'column')}, 'text': '세 배 계산'} for target in explanations.column_targets(run)],
                'transformations': [{**{k: target[k] for k in ('step_no', 'transformation_no')}, 'text': '원본 x 값에 3을 곱해 y 열을 만듭니다.'} for target in explanations.transformation_targets(run)]}, False

    monkeypatch.setattr(explanations, 'obtain', obtain)
    described = client.post(decision + '/explanations').json()
    assert described['pending_revision']['explanation_status'] == 'ready'
    stage = described['pending_revision']['stage']
    assert all(item['description']['source'] == 'llm' for item in stage['transformations'])
    for condition in ('ex', 'in-situ'):
        changed = client.post(url + '/condition', json={'condition': condition}).json()
        assert changed['pending_revision']['stage'] == stage
        assert changed['run']['id'] == base['id']
    client.post(decision + '/deny')
    assert client.post(decision + '/explanations').status_code == 409


def test_capability_preview_also_stops_before_downstream(workspace):
    client, url, body, base, generator, *_ = workspace
    stored = server.read(url.rsplit('/', 1)[-1])
    stored['execution_engine'] = 'capability'
    stored['runs'][0]['pipeline']['engine'] = 'capability'
    server.save(stored)
    generator.changes = [{'action': 'replace', 'step_id': base['stages'][2]['id'], 'code': "second = first.assign(z=first['x'] * 3)"}]
    session, _ = propose(workspace)
    assert session['pending_revision']['stage']['table']['columns'] == ['x', 'z']


def test_slow_approval_keeps_original_and_candidate_readable_and_rejects_second_decision(workspace, monkeypatch):
    client, url, _, base, *_ = workspace
    session, decision = propose(workspace)
    entered, release = threading.Event(), threading.Event()
    execute = server.execute

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return execute(*args, **kwargs)

    monkeypatch.setattr(server, 'execute', slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(client.post, decision + '/approve')
        assert entered.wait(3)
        try:
            observed = pool.submit(client.get, url).result(timeout=2).json()
            assert observed['run']['id'] == base['id']
            assert observed['pending_revision']['status'] == 'approving'
            assert observed['pending_revision']['stage'] == session['pending_revision']['stage']
            assert client.post(decision + '/approve').status_code == 409
            assert client.post(decision + '/deny').status_code == 409
        finally:
            release.set()
        approved = future.result(timeout=8).json()
        assert approved['pending_revision'] is None and approved['run']['id'] != base['id']


def test_explanation_cannot_reintroduce_a_denied_candidate(workspace, monkeypatch):
    client, _, _, base, *_ = workspace
    _, decision = propose(workspace)

    def obtain(*args, **kwargs):
        assert client.post(decision + '/deny').status_code == 200
        raise ValueError('late explanation')

    monkeypatch.setattr(explanations, 'obtain', obtain)
    assert client.post(decision + '/explanations').status_code == 409
    session = client.get(workspace[1]).json()
    assert session['pending_revision'] is None and session['run']['id'] == base['id']


def test_selected_transformation_context_is_passed_to_scope_inference(workspace):
    client, url, body, base, generator, calls = workspace
    selected = next(t for t in base['stages'][2]['transformations'] if 'y' in t['output_columns'])
    generator.scope = 'transformation'
    context = {**body['context'], 'transformation_id': selected['id'], 'execution_version': base['id']}
    session = client.post(url + '/revision-preview', json={**body, 'context': context}).json()
    assert session['pending_revision']['status'] == 'ready'
    assert session['pending_revision']['scope'] == 'transformation'
    assert calls[0]['selected_transformation']['id'] == selected['id']
    assert 'source_context' not in calls[0]['selected_transformation']


@pytest.mark.parametrize('condition', ['in-situ', 'ex'])
def test_chat_review_prose_survives_both_decisions_and_reload(workspace, condition):
    client, url, _, base, generator, *_ = workspace
    client.post(url + '/condition', json={'condition': condition})
    generator.assumptions = ['x 값에 3을 곱해 y를 계산합니다.', '다른 Step의 코드는 유지합니다.']
    expected = []
    for action, status in [('deny', 'denied'), ('approve', 'approved')]:
        session, decision = propose(workspace)
        preview = session['pending_revision']
        decided = client.post(decision + '/' + action).json()
        entry = decided['revision_history'][-1]
        assert entry['id'] == preview['id'] and entry['label'] == 'Step 2a'
        assert entry['request'] == preview['request']
        assert entry['assumptions'] == preview['assumptions'] == generator.assumptions
        assert entry['status'] == status and entry['decided_at']
        assert set(entry).isdisjoint({'plan', 'preview_run', 'stage', 'step_code'})
        if action == 'approve':
            assert entry['run_id'] == decided['run']['id']
        else:
            assert decided['run']['id'] == base['id'] and 'run_id' not in entry
        expected.append(entry)
        assert decided['pending_revision'] is None
        assert client.get(url).json()['revision_history'] == expected
        assert server.participant_view(client.get(url).json())['revision_history'] == expected
        assert client.post(decision + '/' + action).status_code == 409
        assert client.get(url).json()['revision_history'] == expected


@pytest.mark.parametrize('condition', ['in-situ', 'ex'])
def test_chat_undo_restores_exact_saved_results_and_retains_review_prose(workspace, condition, monkeypatch):
    client,url,_,base,generator,*_=workspace
    client.post(url+'/condition',json={'condition':condition})
    generator.assumptions=['x 값에 3을 곱해 y를 계산합니다.']
    _,decision=propose(workspace)
    approved=client.post(decision+'/approve').json()
    history=copy.deepcopy(approved['revision_history'])
    def unexpected_execution(*args,**kwargs):raise AssertionError('Undo must restore the saved run, never execute code or call the model.')
    monkeypatch.setattr(server,'execute',unexpected_execution)
    response=client.post(url+'/undo',json={'base_run_id':approved['run']['id']})
    assert response.status_code==200,response.text
    undone=response.json()
    assert undone['run']['id']==base['id'] and undone['run']['code']==base['code']
    assert [s['table'] for s in undone['run']['stages']]==[s['table'] for s in base['stages']]
    assert len(undone['runs'])==2 and undone['revision_history']==history
    restored=client.get(url).json()
    assert restored['run']['id']==base['id'] and restored['revision_history']==history
    assert client.post(url+'/undo',json={'base_run_id':approved['run']['id']}).status_code==409
    assert client.get(url).json()['run']['id']==base['id']
