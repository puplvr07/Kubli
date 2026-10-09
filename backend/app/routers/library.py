import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from app.dependencies import unlocked
from app.schemas import AskInput, CompletenessInput
from app.services.parsing import parse_file, chunk_pages
from app.services.deid import scan
from app.services import llm
from app.services.rag import valid_vectors, answer, retrieve, missing_items, citation

router = APIRouter(prefix='/api')
TAGS = {'notes', 'guidelines', 'textbook'}


def document_summary(document: dict) -> dict:
    return {key: document[key] for key in ('id', 'title', 'tag', 'timestamp', 'chunks', 'sample')}


async def prepare_document(filename: str, pages, tag: str, sample: bool = False, vault=None, token=None):
    document_id = str(uuid4())
    pieces = chunk_pages(pages, filename)
    if len(pieces) > 2000:
        raise HTTPException(422, 'Too many chunks. Split this document locally.')
    vectors = []
    for start in range(0, len(pieces), 16):
        if vault is not None:
            vault.authorize(token, touch=False)
        batch = pieces[start:start + 16]
        vectors.extend(valid_vectors(await llm.embed_documents([c['text'] for c in batch]), len(batch)))
    for piece, embedding in zip(pieces, vectors):
        piece.update(id=str(uuid4()), document_id=document_id, tag=tag, embedding=embedding,
                     embedding_model=llm.EMBEDDING_PROFILE)
    document = {'id': document_id, 'title': filename, 'tag': tag, 'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'chunks': len(pieces), 'sample': sample}
    return document, pieces

@router.post('/library/upload')
async def upload(vault=Depends(unlocked), files: list[UploadFile] = File(...), tag: str = Form('notes'),
                 ocr: bool = Form(False), proceed: bool = Form(False), deid_keep: str = Form('{}')):
    token = vault.token
    if tag not in TAGS:
        raise HTTPException(422, 'Tag must be notes, guidelines or textbook.')
    if not 1 <= len(files) <= 10:
        raise HTTPException(422, 'Upload 1–10 files at a time.')
    try:
        approvals = json.loads(deid_keep)
        if not isinstance(approvals, dict): raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, 'Invalid identifier review choices.') from None
    parsed = []
    reviews = []
    total = 0
    for file in files:
        filename = Path((file.filename or 'document').replace('\\', '/')).name[:160]
        content = await file.read(20 * 1024 * 1024 + 1)
        total += len(content)
        if len(content) > 20 * 1024 * 1024 or total > 30 * 1024 * 1024:
            raise HTTPException(413, 'Limit: 20 MB per file and 30 MB combined.')
        pages = parse_file(filename, content, ocr)
        flagged = scan(filename, 'filename') + [dict(flag, page=page.page) for page in pages for flag in scan(page.text, f'page:{page.page}')]
        parsed.append((filename, pages))
        reviews.append({'filename': filename, 'flags': flagged, 'pages': len(pages), 'chunks': len(chunk_pages(pages, filename))})
    if not proceed:
        return {'needs_review': True, 'files': reviews, 'notice': 'Warning aid only, not a de-identification guarantee. No files have been indexed or saved.'}
    for review in reviews:
        choices = approvals.get(review['filename'], [])
        if not isinstance(choices, list) or any(flag['id'] not in choices for flag in review['flags']):
            raise HTTPException(409, 'Review identifiers for every included file before indexing. Cancel or exclude files you do not want to keep.')
    items = []
    chunks = []
    documents = []
    for filename, pages in parsed:
        document, pieces = await prepare_document(filename, pages, tag, vault=vault, token=token)
        documents.append(document)
        items.append(('document', document)); items.extend(('chunk', piece) for piece in pieces)
        chunks.extend(pieces)
    vault.authorize(token, touch=False)
    vault.put_many(items)
    vault.index.extend(chunks)
    return {'needs_review': False, 'documents': [document_summary(d) for d in documents], 'chunks_indexed': len(chunks)}

@router.get('/library')
def list_library(vault=Depends(unlocked)):
    return [document_summary(document) for document in vault.list('document')]

@router.delete('/library/{item_id}')
def delete_document(item_id: str, vault=Depends(unlocked)):
    vault.delete_document(item_id)
    return {'deleted': True}

@router.post('/library/reindex')
async def reindex(vault=Depends(unlocked)):
    token = vault.token
    # Copy index; old encrypted embeddings stay intact until replacement is complete.
    snapshot = list(vault.index)
    replacements = []
    for start in range(0, len(snapshot), 16):
        vault.authorize(token, touch=False)
        batch = snapshot[start:start + 16]
        vectors = valid_vectors(await llm.embed_documents([chunk['text'] for chunk in batch]), len(batch))
        replacements.extend(dict(chunk, embedding=vector, embedding_model=llm.EMBEDDING_PROFILE)
                            for chunk, vector in zip(batch, vectors))
    vault.authorize(token, touch=False)
    if {c['id'] for c in snapshot} != {c['id'] for c in vault.index}:
        raise HTTPException(409, 'Library changed while reindexing. Retry after indexing/deletion finishes.')
    vault.put_many([('chunk', c) for c in replacements])
    vault.index = replacements
    return {'chunks_indexed': len(replacements)}

@router.post('/library/ask')
async def ask(body: AskInput, vault=Depends(unlocked)):
    return await answer(vault, body.question, body.scope, vault.token)

@router.post('/completeness')
async def completeness(body: CompletenessInput, vault=Depends(unlocked)):
    query = ' '.join(value for value in [body.record.chief_complaint, body.record.assessment] if value)
    chunks = await retrieve(vault, query, ['notes', 'guidelines'], vault.token) if query else []
    if not chunks:
        return {'flags': [], 'message': 'No matching material found in your library.'}
    flags = missing_items(body.record.model_dump(), chunks)
    return {'flags': flags, 'message': 'Documentation prompts from your local sources; verify their relevance.' if flags else 'No additional missing checklist items identified. This is not a clinical completeness guarantee.'}
