"""Opt-in RAG tests against real, pre-pulled local Ollama models."""
import asyncio
import os
import re
import time

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


def test_paraphrase_with_zero_keyword_overlap_answers_with_verbatim_citation(live_library):
    assert terms(QUESTION).isdisjoint(terms(SOURCE_TEXT))
    result = ask_live(live_library)
    assert result['status'] == 'answered', result
    assert result['citations'], result
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
        result = ask_live(live_library)
        assert result['status'] == 'answered', f'run {run + 1}: {result}'
        assert result['answer'].strip(), f'run {run + 1}: empty answer'
        assert result['citations'], f'run {run + 1}: no citations'
        assert_generation_finished(result)
