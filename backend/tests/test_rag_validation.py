import asyncio
import json

import pytest

from app.schemas import RAGResponse
from app.services import llm
from app.services.rag import NOT_COVERED, answer
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
def test_invalid_source_ids_retry_then_raise_model_error(tmp_path, monkeypatch, bad_source_id):
    vault = Vault(tmp_path)
    token = vault.unlock('strong password')
    vault.index = [make_chunk()]

    async def embedding(question):
        return [1.0, 0.0]

    async def fake_post(path, body, timeout_seconds=180):
        return ollama_result({
            'status': 'answered', 'answer': 'An unsupported answer.',
            'source_ids': [bad_source_id],
        })

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    with pytest.raises(llm.ModelGenerationError) as failure:
        asyncio.run(answer(vault, 'Why do polar lights occur?', ['textbook'], token))
    assert failure.value.reason == 'answer_validation'
    vault.close()


def test_backend_selects_source_and_verified_exact_quote_when_model_omits_id(tmp_path, monkeypatch):
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
            'answer': 'Auroras occur when charged particles interact with the upper atmosphere.',
        })

    monkeypatch.setattr(llm, 'embed_query', embedding)
    monkeypatch.setattr(llm, 'local_post', fake_post)
    result = asyncio.run(answer(vault, 'Why do auroras occur?', ['textbook'], token))
    assert result['status'] == 'answered'
    assert result['citations'][0]['chunk_id'] == 'known-chunk'
    assert result['citations'][0]['snippet'] in result['citations'][0]['context']
    vault.close()


def test_model_error_has_distinct_http_response(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv('WARDNOTE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        token = client.post('/api/unlock', json={'password': 'strong password'}).json()['token']
        app.state.vault.index = [make_chunk()]

        async def embedding(question):
            return [1.0, 0.0]

        async def failed(*args, **kwargs):
            raise llm.ModelGenerationError('invalid_json')

        monkeypatch.setattr(llm, 'embed_query', embedding)
        monkeypatch.setattr(llm, 'generate_validated', failed)
        response = client.post('/api/library/ask', headers={'Authorization': f'Bearer {token}'},
                               json={'question': 'Why do polar lights occur?', 'scope': ['textbook']})
    assert response.status_code == 502
    assert response.json()['status'] == 'model_error'
    assert response.json()['detail'] != NOT_COVERED
