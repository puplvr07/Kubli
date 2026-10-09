import asyncio
import json

import pytest

from app.schemas import RAGModelResponse, RAGResponse
from app.services import llm
from app.services.rag import NOT_COVERED, answer, source_evidence
from app.services.store import Vault


def ollama_result(payload: dict, *, done_reason: str = 'stop', eval_count: int = 20) -> dict:
    return {
        'message': {'content': json.dumps(payload)},
        'done': True,
        'done_reason': done_reason,
        'eval_count': eval_count,
    }


def make_chunk() -> dict:
    return {
        'id': 'known-chunk', 'document_id': 'doc',
        'text': 'The aurora appears when charged particles interact with the upper atmosphere.',
        'filename': 'science.txt', 'page': 1, 'heading': 'Aurora', 'tag': 'textbook',
        'embedding': [1.0, 0.0], 'embedding_model': llm.EMBEDDING_PROFILE,
    }


def test_empty_object_retries_then_model_error(monkeypatch):
    calls = 0

    async def fake_post(path, body, timeout_seconds=180):
        nonlocal calls
        calls += 1
        return ollama_result({})

    monkeypatch.setattr(llm, 'local_post', fake_post)
    with pytest.raises(llm.ModelGenerationError) as failure:
        asyncio.run(llm.generate_validated('prompt', RAGResponse, data={'question': 'test'}))
    assert calls == 2
    assert failure.value.reason == 'schema_validation'


def test_truncation_retries_and_uses_second_complete_response(monkeypatch):
    results = [
        ollama_result({'status': 'not_covered', 'answer': NOT_COVERED, 'citations': []},
                      done_reason='length', eval_count=llm.RAG_NUM_PREDICT),
        ollama_result({'status': 'not_covered', 'answer': NOT_COVERED, 'citations': []},
                      eval_count=18),
    ]

    async def fake_post(path, body, timeout_seconds=180):
        assert body['options']['num_predict'] == llm.RAG_NUM_PREDICT
        assert 0 < timeout_seconds <= llm.RAG_TIMEOUT_SECONDS
        return results.pop(0)

    monkeypatch.setattr(llm, 'local_post', fake_post)
    generated = asyncio.run(llm.generate_validated('prompt', RAGResponse, data={}))
    assert generated.value.status == 'not_covered'
    assert generated.metadata['done_reason'] == 'stop'
    assert not results


def test_valid_not_covered_is_accepted(monkeypatch):
    async def fake_post(path, body, timeout_seconds=180):
        return ollama_result({'status': 'not_covered', 'answer': NOT_COVERED, 'citations': []})

    monkeypatch.setattr(llm, 'local_post', fake_post)
    generated = asyncio.run(llm.generate_validated('prompt', RAGResponse, data={}))
    assert generated.value.model_dump() == {
        'status': 'not_covered', 'answer': NOT_COVERED, 'citations': [],
    }


@pytest.mark.parametrize('bad_source_id', ['known-chunk', 'S99'])
def test_invalid_source_ids_are_recovered_from_matching_source_text(tmp_path, monkeypatch, bad_source_id):
    vault = Vault(tmp_path)
    token = vault.unlock('strong password')
    vault.index = [make_chunk()]

    async def embedding(question):
        return [1.0, 0.0]

    async def fake_post(path, body, timeout_seconds=180):
        return ollama_result({
            'status': 'answered', 'answer': make_chunk()['text'],
            'source_ids': [bad_source_id],
        })

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    result = asyncio.run(answer(vault, 'Why do polar lights occur?', ['textbook'], token))
    assert result['status'] == 'answered'
    assert result['answer'] == make_chunk()['text']
    assert result['citations'][0]['chunk_id'] == 'known-chunk'
    vault.close()


@pytest.mark.parametrize('source_ids', [['S1'], ['S99']])
def test_unsupported_prose_still_fails_closed(tmp_path, monkeypatch, source_ids):
    vault = Vault(tmp_path)
    token = vault.unlock('strong password')
    vault.index = [make_chunk()]

    async def embedding(question):
        return [1.0, 0.0]

    async def fake_post(path, body, timeout_seconds=180):
        return ollama_result({'status': 'answered', 'answer': 'Saturn has icy rings.',
                              'source_ids': source_ids})

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    with pytest.raises(llm.ModelGenerationError) as failure:
        asyncio.run(answer(vault, 'Why do polar lights occur?', ['textbook'], token))
    assert failure.value.reason == 'answer_validation'
    vault.close()


def test_backend_selects_source_and_exact_quote_when_model_omits_id(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    token = vault.unlock('strong password')
    vault.index = [make_chunk()]

    async def embedding(question):
        return [1.0, 0.0]

    async def fake_post(path, body, timeout_seconds=180):
        supplied = json.loads(body['messages'][1]['content'])['chunks']
        assert supplied[0]['source_id'] == 'S1'
        assert 'chunk_id' not in supplied[0]
        return ollama_result({
            'status': 'answered',
            'answer': make_chunk()['text'],
        })

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    result = asyncio.run(answer(vault, 'Why do auroras occur?', ['textbook'], token))
    assert result['status'] == 'answered'
    assert result['answer'] == make_chunk()['text']
    assert result['citations'][0]['chunk_id'] == 'known-chunk'
    assert result['citations'][0]['snippet'] == result['answer']
    assert result['citations'][0]['filename'] == 'science.txt'
    assert result['citations'][0]['page'] == 1
    vault.close()


@pytest.mark.parametrize('answer_text, source_id', [
    ('The aurora appears when charged particles interact with the upper atmosphere. It is green.', 'S1'),
    ('Charged particles make every aurora green.', 'S1'),
    ('The aurora appears when charged particles interact with the upper atmosphere.', 'S2'),
])
def test_generated_claims_are_replaced_by_exact_source_text(tmp_path, monkeypatch, answer_text, source_id):
    vault = Vault(tmp_path)
    token = vault.unlock('strong password')
    vault.index = [make_chunk(), dict(make_chunk(), id='other-chunk',
                                      text='Yeast makes bread rise.', filename='bread.txt')]

    async def embedding(question):
        return [1.0, 0.0]

    async def fake_post(path, body, timeout_seconds=180):
        return ollama_result({'status': 'answered', 'answer': answer_text,
                              'source_ids': [source_id]})

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    result = asyncio.run(answer(vault, 'Why do auroras occur?', ['textbook'], token))
    assert result['status'] == 'answered'
    assert result['answer'] == make_chunk()['text']
    assert result['citations'][0]['snippet'] == make_chunk()['text']
    assert 'green' not in result['answer'].lower()
    vault.close()


@pytest.mark.parametrize('payload', [
    {'answer': 'Charged particles interact with the upper atmosphere.', 'source_id': 'S1'},
    {'status': 'answer', 'response': 'Charged particles interact with the upper atmosphere.',
     'citations': [{'chunk_id': 'S1'}], 'extra_comment': 'ignored'},
])
def test_small_model_shape_is_normalized(payload):
    result = RAGModelResponse.model_validate(payload)
    assert result.status == 'answered'
    assert result.source_ids == ['S1']


def test_genuine_missing_coverage_keeps_refusal(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    token = vault.unlock('strong password')
    vault.index = [make_chunk()]

    async def embedding(question):
        return [1.0, 0.0]

    async def fake_post(path, body, timeout_seconds=180):
        return ollama_result({'status': 'not_covered', 'answer': NOT_COVERED,
                              'source_ids': []})

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    result = asyncio.run(answer(vault, 'What insulin dose is stated?', ['textbook'], token))
    assert result['status'] == 'not_covered'
    assert result['answer'] == NOT_COVERED
    assert result['citations'] == []
    vault.close()


@pytest.mark.parametrize('reason, message', [
    ('invalid_json', 'invalid JSON'),
    ('schema_validation', 'incomplete response'),
    ('truncated', 'cut off'),
    ('unreachable', 'not running'),
    ('timeout', 'timed out'),
    ('request_failed', 'rejected the request'),
    ('invalid_service_response', 'service returned an invalid response'),
])
def test_model_error_has_distinct_http_response(tmp_path, monkeypatch, reason, message):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv('WARDNOTE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        token = client.post('/api/unlock', json={'password': 'strong password'}).json()['token']
        app.state.vault.index = [make_chunk()]

        async def embedding(question):
            return [1.0, 0.0]

        async def failed(*args, **kwargs):
            raise llm.ModelGenerationError(reason)

        monkeypatch.setattr(llm, 'embed_query', embedding)
        monkeypatch.setattr(llm, 'generate_validated', failed)
        response = client.post('/api/library/ask', headers={'Authorization': f'Bearer {token}'},
                               json={'question': 'Why do polar lights occur?', 'scope': ['textbook']})
    assert response.status_code == 502
    assert response.json()['status'] == 'model_error'
    assert response.json()['detail'] != NOT_COVERED
    assert message in response.json()['detail']


@pytest.mark.parametrize('reason', ['unreachable', 'timeout', 'request_failed'])
def test_transport_failure_does_not_reuse_previous_invalid_output(monkeypatch, reason):
    calls = 0

    async def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ollama_result({})
        raise llm.LocalModelError(reason, 'Fictional service failure')

    monkeypatch.setattr(llm, 'local_post', fake_post)
    with pytest.raises(llm.ModelGenerationError) as failure:
        asyncio.run(llm.generate_validated('prompt', RAGResponse, data={}))
    assert calls == 2
    assert failure.value.reason == reason
    assert failure.value.raw_output == ''
    assert failure.value.metadata == {}


def test_evidence_requires_similarity_and_specific_terms_and_is_bounded():
    chunks = [dict(make_chunk(), id=str(i), text='SOAP means study notes. ' + str(i) + 'x' * 1700,
                   similarity=0.8) for i in range(5)]
    assert source_evidence(chunks, 'What metformin dosage is stated in the library?') == []
    assert source_evidence([dict(chunks[0], similarity=0.1)], 'SOAP') == []
    result = source_evidence(chunks, 'What does SOAP stand for?')
    assert len(result) == 3
    assert all(len(c['snippet']) <= 1600 and c['snippet'] in c['context'] for c in result)
    assert all(c['filename'] == 'science.txt' and c['page'] == 1 for c in result)


@pytest.mark.parametrize('failure', ['refusal', 'invalid_json', 'truncated', 'timeout', 'unreachable', 'answer_validation'])
def test_evidence_survives_answer_failure_without_becoming_an_answer(tmp_path, monkeypatch, failure):
    vault = Vault(tmp_path)
    token = vault.unlock('fictional smoke password')
    vault.index = [make_chunk()]

    async def embedding(question):
        return [1.0, 0.0]

    async def fake_post(*args, **kwargs):
        if failure == 'refusal':
            return ollama_result({'status': 'not_covered', 'answer': NOT_COVERED, 'source_ids': []})
        raise llm.ModelGenerationError(failure)

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    result = asyncio.run(answer(vault, 'What makes the aurora?', ['textbook'], token))
    assert result['status'] == 'evidence'
    assert result['answer'] == '' and result['citations'] == []
    assert result['evidence'][0]['snippet'] == make_chunk()['text']
    if failure == 'refusal':
        assert result['model_error'] is None
    else:
        assert result['model_error']['reason'] == failure
    vault.close()


def test_fallback_rechecks_authentication_after_model_failure(tmp_path, monkeypatch):
    from fastapi import HTTPException
    vault = Vault(tmp_path)
    token = vault.unlock('fictional smoke password')
    vault.index = [make_chunk()]

    async def embedding(question):
        return [1.0, 0.0]

    async def failed(*args, **kwargs):
        vault.lock()
        raise llm.ModelGenerationError('timeout')

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'generate_validated', failed)
    with pytest.raises(HTTPException) as error:
        asyncio.run(answer(vault, 'What makes the aurora?', ['textbook'], token))
    assert error.value.status_code == 401
    vault.close()
