"""Opt-in integration: actual local Ollama, no mocks or hidden fallback."""
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

pytestmark = pytest.mark.skipif(os.getenv('WARDNOTE_LIVE_MODELS') != '1', reason='Opt-in: needs pre-pulled real local Ollama models')

@pytest.fixture
def local_client(tmp_path, monkeypatch):
    monkeypatch.setenv('WARDNOTE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        result = client.post('/api/unlock', json={'password':'fictional integration password'})
        assert result.status_code == 200
        client.headers['Authorization'] = 'Bearer ' + result.json()['token']
        yield client


def test_real_structure_preserves_stated_vitals_and_no_invented_diagnosis(local_client):
    response = local_client.post('/api/structure', json={'text':'28-year-old female. Chief complaint: chest pain. BP 118/76, HR 88, RR 18, temperature 36.8 C, SpO2 98%. No assessment or plan was stated.'})
    assert response.status_code == 200, response.json().get('detail', 'structure failed')
    record = response.json()['record']
    assert record['patient']['age'] == 28
    assert record['chief_complaint'] == 'chest pain'
    assert record['vitals']['hr'] == 88
    assert record['assessment'] is None and record['plan'] is None
    assert local_client.get('/api/records').json() == []


def test_real_sample_library_citations_and_refusal(local_client):
    uploaded = local_client.post('/api/demo/library', json={})
    assert uploaded.status_code == 200, uploaded.json().get('detail', 'index failed')
    assert len(local_client.get('/api/library').json()) == 4
    response = local_client.post('/api/library/ask', json={'question':'What does SOAP stand for?', 'scope':['notes']})
    assert response.status_code == 200
    result = response.json()
    assert result['status'] in {'answered', 'evidence'}
    passages = result['citations'] or result.get('evidence', [])
    assert passages and any('Subjective' in c['snippet'] for c in passages)
    assert all(c['snippet'] in c['context'] for c in passages)
    refusal = local_client.post('/api/library/ask', json={'question':'What is the insulin regimen?', 'scope':['notes','guidelines','textbook']})
    assert refusal.status_code == 200
    assert refusal.json()['status'] == 'not_covered'
    assert refusal.json()['answer'] == 'Not covered by your library'
    assert refusal.json()['citations'] == []
