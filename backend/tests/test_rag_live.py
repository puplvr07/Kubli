"""Opt-in RAG tests against real, pre-pulled local Ollama models."""
import asyncio
import os
import re
import time
from pathlib import Path

import pytest

from app.routers.library import prepare_document
from app.services import llm
from app.services.parsing import PageText
from app.services.rag import NOT_COVERED, answer, terms
from app.services.store import Vault


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv('RUN_LIVE_MODEL_TESTS') != '1',
        reason='Set RUN_LIVE_MODEL_TESTS=1 to run real local Ollama RAG tests.',
    ),
]

QUESTION = 'What creates the glowing ribbons seen near the poles?'
SOURCE_TEXT = (
    "Auroral displays arise when energetic solar particles collide with gases high in Earth's atmosphere. "
    'Those collisions release light in shifting arcs and curtains.'
)


@pytest.fixture(scope='module')
def live_library(tmp_path_factory):
    vault = Vault(tmp_path_factory.mktemp('rag-live'))
    token = vault.unlock('fictional live test password')
    documents = [
        ('aurora.txt', 'textbook', SOURCE_TEXT),
        ('bread.txt', 'notes', 'Yeast fermentation produces carbon dioxide that expands dough during bread making.'),
        ('compass.txt', 'guidelines', 'A magnetic compass aligns with the local magnetic field and indicates direction.'),
        ('leaves.txt', 'textbook', 'Chlorophyll absorbs light energy used during photosynthesis in green plants.'),
    ]
    try:
        for filename, tag, text in documents:
            document, chunks = asyncio.run(prepare_document(
                filename, [PageText(1, text, filename.removesuffix('.txt'))], tag,
                vault=vault, token=token,
            ))
            vault.put_many([('document', document), *(('chunk', chunk) for chunk in chunks)])
            vault.index.extend(chunks)
    except Exception as exc:
        vault.close()
        pytest.fail(f'Live RAG setup could not reach the required local models: {type(exc).__name__}: {exc}')
    yield vault, token
    vault.close()


def ask_live(live_library, question=QUESTION):
    vault, token = live_library
    started = time.monotonic()
    try:
        result = asyncio.run(answer(vault, question, ['notes', 'guidelines', 'textbook'], token))
    except llm.ModelGenerationError as exc:
        pytest.fail(
            f'Live model response failed validation ({exc.reason}); '
            f'raw model output for this test only: {exc.raw_output!r}'
        )
    elapsed = time.monotonic() - started
    assert elapsed < llm.RAG_TIMEOUT_SECONDS, (
        f'RAG call took {elapsed:.2f}s; configured limit is {llm.RAG_TIMEOUT_SECONDS:.2f}s'
    )
    return result


def assert_generation_finished(result):
    generation = result['_debug']['generation']
    assert generation['done_reason'] != 'length', generation
    assert isinstance(generation['eval_count'], int), generation
    assert generation['eval_count'] < generation['num_predict'], generation


def test_zero_keyword_overlap_keeps_retrieval_but_does_not_force_evidence(live_library):
    assert terms(QUESTION).isdisjoint(terms(SOURCE_TEXT))
    result = ask_live(live_library)
    vault, _ = live_library
    best = next(c for c in vault.index if c['id'] == result['_debug']['retrieved'][0]['chunk_id'])
    assert best['filename'] == 'aurora.txt'
    assert result['status'] in {'answered', 'not_covered'}, result
    if result['status'] == 'not_covered':
        assert not result['citations'] and not result.get('evidence')
    else:
        assert result['citations']
    for citation in result['citations']:
        normalized_context = re.sub(r'\s+', ' ', citation['context']).casefold()
        normalized_quote = re.sub(r'\s+', ' ', citation['quote']).casefold()
        assert normalized_quote in normalized_context
    assert_generation_finished(result)


def test_uncovered_question_returns_valid_not_covered(live_library):
    result = ask_live(live_library, 'What dosage of metformin is stated in these chunks?')
    assert result['status'] == 'not_covered', result
    assert result['answer'] == NOT_COVERED
    assert result['citations'] == []
    assert_generation_finished(result)


def test_repeated_question_never_returns_empty_or_invalid_output(live_library):
    for run in range(5):
        result = ask_live(live_library, 'What happens when solar particles collide?')
        assert result['status'] in {'answered', 'evidence'}, f'run {run + 1}: {result}'
        passages = result['citations'] or result.get('evidence', [])
        assert passages and all(c['snippet'] in c['context'] for c in passages)
        assert any(c['filename'] == 'aurora.txt' for c in passages)


@pytest.fixture(scope='module')
def sample_api(tmp_path_factory):
    from fastapi.testclient import TestClient
    from app.main import app

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('WARDNOTE_DATA_DIR', str(tmp_path_factory.mktemp('fictional-sample-live')))
        with TestClient(app) as client:
            response = client.post('/api/unlock', json={'password': 'fictional smoke password'})
            assert response.status_code == 200
            client.headers['Authorization'] = 'Bearer ' + response.json()['token']
            imported = client.post('/api/demo/library', json={})
            assert imported.status_code == 200, imported.json()
            assert len(client.get('/api/library').json()) == 4
            yield client, app


@pytest.mark.parametrize('question, expected_status, filename, expected_text', [
    *[('What does SOAP stand for?', 'answered', 'sample-notes.md',
       'SOAP stands for Subjective, Objective, Assessment, and Plan.') for _ in range(5)],
    *[('What dosage of metformin is stated in the library?', 'not_covered', None, None) for _ in range(5)],
    *[('What does SOAP stand for and what is the metformin dose?', 'evidence', 'sample-notes.md',
       'SOAP stands for Subjective, Objective, Assessment, and Plan.') for _ in range(5)],
    ('What should a chest pain example document about onset?', 'answered',
     'chest-pain-sample.txt', 'symptom onset and duration.'),
])
def test_sample_api_reliability(sample_api, caplog, question, expected_status, filename, expected_text):
    client, app = sample_api
    response = client.post('/api/library/ask', json={
        'question': question, 'scope': ['notes', 'guidelines', 'textbook'],
    })
    result = response.json()
    failures = [entry.getMessage() for entry in caplog.records
                if 'rag_generation_failed' in entry.getMessage()]
    print({'question': question, 'http': response.status_code,
           'status': result.get('status'), 'answer': result.get('answer'),
           'sources': [c['filename'] for c in result.get('evidence', result.get('citations', []))],
           'error': result.get('model_error', result.get('detail')), 'retry_failures': failures})
    assert response.status_code == 200, result
    assert result['status'] in ({'answered', 'evidence'} if expected_status == 'answered' else {expected_status}), result
    if not result.get('model_error'):
        assert_generation_finished(result)
    if expected_status == 'not_covered':
        assert result['answer'] == NOT_COVERED
        assert result['citations'] == []
        return
    passages = result['citations'] or result.get('evidence', [])
    assert any(c['filename'] == filename and expected_text in c['snippet'] for c in passages)
    if result['status'] == 'evidence':
        assert result['answer'] == '' and result['citations'] == []
    for cited in passages:
        assert cited['page'] == 1 and cited['location_type'] == 'page'
        assert cited['quote'] == cited['snippet']
        chunk = next(c for c in app.state.vault.index if c['id'] == cited['chunk_id'])
        assert cited['context'] == chunk['text']
        original = (Path(__file__).resolve().parents[2] / 'guidelines' / cited['filename']).read_bytes().decode('utf-8-sig')
        assert cited['snippet'] in cited['context']
        assert cited['context'] in original
