"""Fresh-checkout handoff contract, without model/network calls."""
import hashlib
import json
from pathlib import Path
from fastapi.testclient import TestClient
import backend.app as server
from backend import candidates

ROOT=Path(__file__).resolve().parents[1]


def test_bundled_catalog_is_self_contained_and_copied_once(tmp_path,monkeypatch):
    manifest=json.loads((ROOT/'tasks/manifest.json').read_text(encoding='utf-8'))
    assert manifest['count']==12
    bundle=tmp_path/'tasks/candidates'
    bundle.mkdir(parents=True)
    for item in manifest['candidates']:
        source=ROOT/'tasks'/item['file']
        raw=source.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        data=json.loads(raw.decode('utf-8-sig'))
        assert data['id']==item['id']
        server.parse_table(data['input_csv']);server.parse_table(data['target_csv'])
        for csv in data.get('sources',{}).values():server.parse_table(csv)
        server.prepare(data['initial_code'],data['steps'],engine='python')
        (bundle/source.name).write_bytes(raw)
    monkeypatch.setattr(candidates,'ROOT',tmp_path)
    monkeypatch.delenv('TRACE_TASK_DIR',raising=False)
    local=candidates.directory()
    assert len(candidates.listing())==12
    first=local/(manifest['candidates'][0]['id']+'.json')
    edited=json.loads(first.read_text(encoding='utf-8-sig'))
    edited['title']='Local edit'
    first.write_text(json.dumps(edited),encoding='utf-8')
    removed=local/(manifest['candidates'][1]['id']+'.json')
    removed.unlink()
    assert candidates.directory()==local
    assert json.loads(first.read_text(encoding='utf-8'))['title']=='Local edit'
    assert not removed.exists()
    override=tmp_path/'explicit-empty'
    monkeypatch.setenv('TRACE_TASK_DIR',str(override))
    assert candidates.listing()==[]


def test_no_login_even_with_stale_credentials_and_same_origin_writes(tmp_path,monkeypatch):
    monkeypatch.delenv('TRACE_LEGACY_AUTH',raising=False)
    monkeypatch.setenv('TRACE_ACCESS_FILE',str(tmp_path/'missing-old-access.json'))
    monkeypatch.setenv('TRACE_TASK_DIR',str(tmp_path/'tasks'))
    monkeypatch.setattr(server,'STORE',tmp_path/'sessions')
    with TestClient(server.app,base_url='https://dev.example.test') as client:
        health=client.get('/api/health').json()
        assert health['access_role']=='local' and not health['team_mode']
        assert not health['pilot_account'] and health['participant_id'] is None
        assert client.get('/login',follow_redirects=False).status_code==404
        assert client.get('/api/task-candidates').status_code==200
        assert client.post('/api/preview',json={'text':'a\n1'},headers={'Origin':'https://dev.example.test'}).status_code==200
        assert client.post('/api/preview',json={'text':'a\n1'},headers={'Origin':'https://other.example.test'}).status_code==403
