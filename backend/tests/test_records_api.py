import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import empty_record
import pymupdf
from fastapi import HTTPException
from app.services.pdf import render_pdf
from app.services.structure import grounded

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
    assert pdf.headers['content-disposition'] == 'attachment; filename="tiboq-draft.pdf"'
    with pymupdf.open(stream=pdf.content, filetype='pdf') as document:
        assert len(document) == 1
        assert 'Not a diagnostic tool' in document[0].get_text()
        assert 'Chest discomfort' in document[0].get_text()
        assert 'TIBOQ' in document[0].get_text()
        assert 'WardNote' not in document[0].get_text()
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


def test_pdf_preserves_all_record_fields_and_rejects_oversize():
    record = empty_record()
    record.patient.age = 28
    record.patient.sex = 'female'
    record.chief_complaint = 'Chest pain'
    record.hpi = 'Pain for two hours'
    record.past_history = 'History unavailable'
    record.medications = ['Drug A', 'Drug B']
    record.allergies = ['Allergen A']
    record.vitals.bp = '118/76'
    record.vitals.hr = 88
    record.vitals.rr = 18
    record.vitals.temp_c = 36.8
    record.vitals.spo2 = 98
    record.physical_exam = 'Alert'
    record.assessment = 'Cause not stated'
    record.plan = 'Present to supervisor'
    saved = {'record': record.model_dump(), 'timestamp': '2026-10-10T12:00:00+00:00'}
    with pymupdf.open(stream=render_pdf(saved), filetype='pdf') as document:
        content = document[0].get_text()
        for expected in ('TIBOQ', '2026-10-10T12:00:00+00:00', 'Age: 28', 'Sex: female',
                         'Chest pain', 'Pain for two hours', 'History unavailable',
                         'Drug A; Drug B', 'Allergen A', '118/76', 'Heart rate: 88',
                         'Respiratory rate: 18', '36.8', '98', 'Alert', 'Cause not stated',
                         'Present to supervisor', 'Not a diagnostic tool'):
            assert expected in content
    record.hpi = 'Long clinical note. ' * 1500
    with pytest.raises(HTTPException, match='too long') as error:
        render_pdf({**saved, 'record': record.model_dump()})
    assert error.value.status_code == 422


def test_pdf_exports_reviewed_extraction_in_its_soap_sections():
    text = ('A 24-year-old male reports a headache since yesterday, described as a dull pain across the forehead. '
            'Pain is rated 4 out of 10. Past history: not stated. Medications: not stated. '
            'Allergies: not stated. Physical examination: awake, alert, and speaking clearly. '
            'Assessment: headache, cause not stated. Plan: present findings to the supervising clinician.')
    record = grounded(empty_record(), text).record
    record.plan = 'present findings to the supervising clinician'
    with pymupdf.open(stream=render_pdf({'record': record.model_dump(), 'timestamp': '2026-10-10T12:00:00+00:00'}),
                      filetype='pdf') as document:
        content = document[0].get_text()
        assert 'SOAP PRACTICE DRAFT / FOR REVIEW AND STUDY ONLY' in content
        subjective = content.split('S  /  SUBJECTIVE')[1].split('O  /  OBJECTIVE')[0]
        objective = content.split('O  /  OBJECTIVE')[1].split('A  /  ASSESSMENT')[0]
        assessment = content.split('A  /  ASSESSMENT')[1].split('P  /  PLAN')[0]
        plan = content.split('P  /  PLAN')[1].split('Draft-support tool')[0]
        assert 'since yesterday' in subjective and '4 out of 10' in subjective
        assert 'Past history: Not stated' in subjective
        assert 'Medications: Not stated' in subjective and 'Allergies: Not stated' in subjective
        assert 'Physical exam: awake, alert, and speaking clearly' in objective
        assert 'headache, cause not stated' in assessment
        assert 'present findings to the supervising clinician' in plan
        assert 'Past history:' not in objective and 'Medications:' not in objective
        assert 'None' not in content


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
