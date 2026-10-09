import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import empty_record
import pymupdf

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('WARDNOTE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        yield client


def login(client):
    result = client.post('/api/unlock', json={'password': 'safe demo password'})
    assert result.status_code == 200
    return {'Authorization': 'Bearer ' + result.json()['token']}


def test_save_gate_encryption_pdf_and_lock(client):
    assert client.get('/api/records').status_code == 401
    headers = login(client)
    record = empty_record().model_dump(); record['chief_complaint'] = 'Chest discomfort'
    assert client.post('/api/records', headers=headers, json={'record': record, 'confirmed': False}).status_code == 422
    saved = client.post('/api/records', headers=headers, json={'record': record, 'confirmed': True})
    assert saved.status_code == 201
    item_id = saved.json()['id']
    listing = client.get('/api/records', headers=headers).json()
    assert listing[0]['chief_complaint'] == 'Chest discomfort'
    pdf = client.get(f'/api/records/{item_id}/pdf', headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    with pymupdf.open(stream=pdf.content, filetype='pdf') as document:
        assert len(document) == 1
        assert 'Not a diagnostic tool' in document[0].get_text()
        assert 'Chest discomfort' in document[0].get_text()
    assert client.post('/api/lock', headers=headers).status_code == 200
    assert client.get(f'/api/records/{item_id}', headers=headers).status_code == 401
    assert client.post('/api/unlock', json={'password': 'bad password'}).status_code == 401


def test_review_and_numeric_acknowledgements(client):
    headers = login(client)
    record = empty_record().model_dump(); record['hpi'] = 'Patient name: Maria Santos'; record['vitals']['hr'] = 400
    review = client.post('/api/review', headers=headers, json=record).json()
    body = {'record': record, 'confirmed': True}
    assert client.post('/api/records', headers=headers, json=body).status_code == 409
    body['deid_keep'] = [f['id'] for f in review['flags']]
    assert client.post('/api/records', headers=headers, json=body).status_code == 409
    body['warning_acknowledgements'] = [w['message'] for w in review['warnings']]
    assert client.post('/api/records', headers=headers, json=body).status_code == 201


def test_cross_origin_rejected_and_private_metadata_hidden(client):
    headers = login(client)
    assert client.get('/api/status').json()['documents'] is None
    assert client.get('/api/records', headers={**headers, 'Origin': 'https://external.example'}).status_code == 403
    assert client.get('/api/status', headers={'Host': 'evil.example'}).status_code == 403


def test_background_autolock_clears_key_without_an_api_call(tmp_path, monkeypatch):
    import time
    monkeypatch.setenv('WARDNOTE_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('AUTO_LOCK_MINUTES', '0.1')
    with TestClient(app) as session:
        headers = login(session)
        master = app.state.vault._key
        assert master is not None
        time.sleep(7.2)
        assert app.state.vault._key is None and app.state.vault.index == []
        assert all(byte == 0 for byte in master)
        assert session.get('/api/records', headers=headers).status_code == 401
