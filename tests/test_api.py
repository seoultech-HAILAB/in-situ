import json

import httpx
import pytest
from fastapi.testclient import TestClient

import backend.app as server
from backend.generator import DEMO_INPUT, DEMO_TARGET, OpenAIGenerator, Proposal, demo_code


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'STORE', tmp_path)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    return TestClient(server.app)


def test_two_conditions_revision_undo_confirm_and_exports(client):
    s = client.post('/api/demo', json={'condition': 'C'}).json()
    sid, rid = s['id'], s['run']['id']
    code = s['run']['code']
    for condition in ['ex', 'in-situ']:
        s = client.post(f'/api/sessions/{sid}/condition', json={'condition': condition}).json()
        assert s['run']['code'] == code and s['run']['id'] == rid
    for _ in range(2):
        assert client.post(f'/api/sessions/{sid}/events', json={'event': 'review_started', 'execution_version': rid, 'condition': 'C'}).status_code == 200
    s = client.post(f'/api/sessions/{sid}/generate', json={'request': '수량이 정확히 2인 주문도 포함하도록 수정해줘.'}).json()
    assert s['status'] == 'ready' and s['run']['comparison']['matches']
    assert s['run']['code_version'] == 2
    assert {stage['execution_version'] for stage in s['run']['stages']} == {s['run']['id']}
    assert {stage['code_version'] for stage in s['run']['stages']} == {2}
    s = client.post(f'/api/sessions/{sid}/undo').json()
    assert s['run']['id'] == rid
    s = client.post(f'/api/sessions/{sid}/generate', json={'request': '수량이 정확히 2인 주문도 포함'}).json()
    assert s['run']['code_version'] == 3
    assert client.post(f'/api/sessions/{sid}/confirm').json()['confirmed']
    exported = client.get(f'/api/sessions/{sid}/export').json()
    assert exported['final_code'] == s['run']['code']
    assert exported['final_output'] == s['run']['stages'][-1]['table']
    events = exported['events']
    assert sum(e['event'] == 'review_started' for e in events) == 1
    assert events[-1]['event'] == 'final_confirmed'
    assert all('session_id' in e and 'timestamp' in e and 'execution_version' in e for e in events)
    assert next(e for e in events if e['event'] == 'revision_requested')['data']['review_ms'] is not None
    assert 'total' in client.get(f'/api/sessions/{sid}/output.csv').text
    replayed = client.post('/api/replay', json={'session': exported, 'condition': 'A', 'run_index': 0}).json()
    assert replayed['run']['code'] == code
    assert not replayed['run']['comparison']['matches']
    assert replayed['id'] != sid


def test_generation_failure_and_execution_failure_do_not_replace_last_success(client, monkeypatch):
    s = client.post('/api/demo', json={}).json()
    sid, rid = s['id'], s['run']['id']
    s = client.post(f'/api/sessions/{sid}/generate', json={'request': '지원하지 않는 데모 수정'}).json()
    assert s['status'] == 'failed' and s['error']['phase'] == 'generation'
    assert s['run']['id'] == rid
    assert client.post(f'/api/sessions/{sid}/confirm').status_code == 422
    client.post(f'/api/sessions/{sid}/undo')
    s = client.post(f'/api/sessions/{sid}/research-code', json={'code': 'result = input_df.head()'}).json()
    assert s['status'] == 'failed' and s['error']['phase'] == 'execution'
    assert s['run']['id'] == rid
    assert s['error']['candidate_code'] == 'result = input_df.head()'


def test_uploaded_data_generation_revision_uses_interface(client, monkeypatch):
    class FakeGenerator:
        calls = []
        def generate(self, inp, target, requirements, code, request, context):
            self.calls.append((inp, target, code, request, context))
            return Proposal(code="s1 = input_df.loc[input_df['units'] >= 2].copy()\nresult = s1.assign(cost=s1['units'] * s1['price'])", assumptions=['테스트 생성기'])
    fake = FakeGenerator()
    monkeypatch.setattr(server, 'generator', fake)
    s = client.post('/api/sessions', json={'input_csv': 'units,price\n1,7\n2,9\n3,5', 'target_csv': 'units,price,cost\n2,9,18\n3,5,15'}).json()
    sid = s['id']
    s = client.post(f'/api/sessions/{sid}/generate', json={}).json()
    assert s['run']['comparison']['matches'] and s['run']['mode'] == 'api'
    s = client.post(f'/api/sessions/{sid}/generate', json={'request': '합계 대신 각 행 유지', 'context': {'step_id': 's1'}}).json()
    assert fake.calls[-1][2] is not None and fake.calls[-1][-1]['step_id'] == 's1'
    assert s['run']['stages'][-1]['table']['rows'][0]['values']['cost'] == 18


def test_no_key_is_not_claimed_as_success(client):
    s = client.post('/api/sessions', json={'input_csv': DEMO_INPUT, 'target_csv': DEMO_TARGET}).json()
    s = client.post(f"/api/sessions/{s['id']}/generate", json={}).json()
    assert s['status'] == 'failed' and s['run'] is None
    assert 'OPENAI_API_KEY' in s['error']['message']


def test_api_provider_request_contract(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    def post(self, url, headers, json):
        assert url.endswith('/responses') and headers['Authorization'] == 'Bearer test-key'
        assert json['text']['format']['type'] == 'json_schema'
        assert json['store'] is False
        task = __import__('json').loads(json['input'])
        assert task['input_csv'] == DEMO_INPUT
        return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': __import__('json').dumps({'code': demo_code(), 'assumptions': []})}]}]})
    monkeypatch.setattr(httpx.Client, 'post', post)
    assert OpenAIGenerator().generate(DEMO_INPUT, DEMO_TARGET, '').code == demo_code()


def test_stale_event_retains_original_version_and_cross_origin_rejected(client):
    s = client.post('/api/demo', json={}).json()
    sid, rid = s['id'], s['run']['id']
    client.post(f'/api/sessions/{sid}/generate', json={'request': '수량이 정확히 2인 주문도 포함'})
    client.post(f'/api/sessions/{sid}/events', json={'event': 'cell_selected', 'execution_version': rid, 'condition': 'C', 'data': {'step_id': 's1'}})
    last = client.get(f'/api/sessions/{sid}/export').json()['events'][-1]
    assert last['execution_version'] == rid and last['code_version'] == 1 and last['condition'] == 'in-situ'
    assert client.post('/api/demo', json={}, headers={'origin': 'https://untrusted.example'}).status_code == 403
