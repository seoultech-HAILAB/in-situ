from fastapi.testclient import TestClient
import backend.app as server


def test_in_situ_has_its_own_export_without_replacing_the_original_page(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'WEB', tmp_path)
    (tmp_path / 'index.html').write_text('<title>original workspace</title>', encoding='utf-8')
    (tmp_path / 'in-situ.html').write_text('<title>in-situ workspace</title>', encoding='utf-8')
    (tmp_path / 'ex-situ.html').write_text('<title>ex-situ workspace</title>', encoding='utf-8')
    client = TestClient(server.app)
    assert client.get('/in-situ').text == '<title>in-situ workspace</title>'
    assert client.get('/').text == '<title>original workspace</title>'
    assert client.get('/ex-situ').text == '<title>ex-situ workspace</title>'
    assert client.get('/ex-situ.html').text == '<title>ex-situ workspace</title>'


def test_missing_in_situ_build_does_not_silently_show_a_different_condition(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'WEB', tmp_path)
    assert TestClient(server.app).get('/in-situ').status_code == 503
    assert TestClient(server.app).get('/ex-situ').status_code == 503
