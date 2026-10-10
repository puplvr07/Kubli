import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
import ipaddress
from starlette.formparsers import MultiPartParser
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.schemas import (StructureInput, StructureResult, UnlockInput, RecoverySetupInput,
                         RecoveryRegenerateInput, RecoverInput)
from app.services.structure import structure
from app.services.store import Vault
from app.services import llm, network
from app.dependencies import unlocked
from app.routers import records, library, demo, voice

# Keep bounded uploads in memory: no plaintext multipart spools on disk.
MultiPartParser.spool_max_size = 32 * 1024 * 1024

class BodyLimitMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get('body', b''))
            if total > 32 * 1024 * 1024:
                raise HTTPException(413, 'Request exceeds the 32 MB in-memory limit.')
            return message
        await self.app(scope, bounded_receive, send)

FRONTEND_ORIGIN = 'http://127.0.0.1:5173'

@asynccontextmanager
async def lifespan(app: FastAPI):
    network.install_guard()
    directory = Path(os.getenv('WARDNOTE_DATA_DIR', str(Path(__file__).resolve().parents[2] / '.wardnote')))
    minutes = float(os.getenv('AUTO_LOCK_MINUTES', '5'))
    if not 0.1 <= minutes <= 60:
        raise RuntimeError('AUTO_LOCK_MINUTES must be between 0.1 and 60.')
    app.state.vault = Vault(directory, minutes)
    async def expiry_loop():
        while True:
            await asyncio.sleep(1)
            app.state.vault.expire()
    task = asyncio.create_task(expiry_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        app.state.vault.close()

app = FastAPI(title='WardNote · local draft support', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN], allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type', 'Authorization'])

@app.middleware('http')
async def privacy_boundary(request: Request, call_next):
    host = request.headers.get('host', '').split(':')[0]
    origin = request.headers.get('origin')
    peer = request.client.host if request.client else '127.0.0.1'
    try:
        local_peer = peer == 'testclient' or ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local_peer = False
    if not local_peer or host not in ('127.0.0.1', 'localhost', 'testserver') or (origin is not None and origin != FRONTEND_ORIGIN):
        return JSONResponse(status_code=403, content={'detail': 'Only the local WardNote frontend may access this backend. Open http://127.0.0.1:5173.'})
    try:
        length = int(request.headers.get('content-length', '0') or 0)
    except ValueError:
        return JSONResponse(status_code=400, content={'detail': 'Invalid request size.'})
    if length < 0 or length > 32 * 1024 * 1024:
        return JSONResponse(status_code=413, content={'detail': 'Upload limit is 32 MB per request.'})
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == '/api/vault/recover':
        return JSONResponse(status_code=422, content={'detail': 'Enter a valid recovery key and a new password of at least 12 characters.'})
    if request.url.path.startswith('/api/vault/recovery/'):
        return JSONResponse(status_code=422, content={'detail': 'Invalid recovery settings request.'})
    if request.url.path == '/api/unlock':
        return JSONResponse(status_code=422, content={'detail': 'Enter a valid vault password.'})
    return JSONResponse(status_code=422, content={'detail': 'Invalid fields. Use the complete record schema, numeric values for vitals, and explicit confirmation when saving.'})

@app.exception_handler(llm.ModelGenerationError)
async def model_generation_error(request: Request, exc: llm.ModelGenerationError):
    messages = {
        'unreachable': 'Ollama is not running. Start the local Ollama service and retry.',
        'request_failed': 'The local Ollama service rejected the request. Check that it is running and has enough memory, then retry.',
        'invalid_service_response': 'The local Ollama service returned an invalid response. Check the service and retry.',
        'model_missing': f'The configured local model is not installed. Run: ollama pull {llm.MODEL}',
        'timeout': 'The local model timed out. Check available RAM or select a smaller OLLAMA_MODEL, then retry.',
        'truncated': 'The local model response was cut off. Please retry.',
        'invalid_json': 'The local model returned invalid JSON. Please retry.',
        'schema_validation': 'The local model returned an incomplete response. Please retry.',
        'citation_validation': 'The local model returned citations that could not be verified. Please retry.',
        'answer_validation': 'The local model answer could not be matched to an exact passage in the selected source. Retry or rephrase your question.',
    }
    return JSONResponse(status_code=502, content={
        'status': 'model_error',
        'detail': messages.get(exc.reason, 'The local model returned an invalid response. Please try again.'),
    })

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    # Never serialize/log exception bodies: parsers or validation may contain patient text.
    return JSONResponse(status_code=500, content={'detail': 'Local operation failed. Nothing from this request was sent outside your device.'})

@app.post('/api/unlock')
def unlock_endpoint(body: UnlockInput, request: Request):
    vault = request.app.state.vault
    token = vault.unlock(body.password)
    return {'token': token, 'auto_lock_minutes': vault.auto_lock_minutes,
            'created': vault.last_unlock_created, 'recovery_configured': vault.recovery_configured,
            'recovery_prompt': vault.recovery_prompt}

@app.post('/api/vault/recovery/setup')
def recovery_setup(body: RecoverySetupInput, vault=Depends(unlocked)):
    recovery_key = vault.setup_recovery(body.enabled)
    return {'configured': vault.recovery_configured, 'recovery_key': recovery_key}

@app.post('/api/vault/recovery/regenerate')
def recovery_regenerate(body: RecoveryRegenerateInput, vault=Depends(unlocked)):
    return {'configured': True, 'recovery_key': vault.regenerate_recovery(body.current_password)}

@app.post('/api/vault/recover')
def recover_vault(body: RecoverInput, request: Request):
    token, recovery_key = request.app.state.vault.recover(
        body.recovery_key, body.new_password, body.generate_new_recovery)
    return {'token': token, 'recovery_configured': recovery_key is not None,
            'recovery_key': recovery_key}

@app.post('/api/lock')
def lock_endpoint(vault=Depends(unlocked)):
    vault.lock()
    return {'locked': True}

@app.post('/api/session/touch')
def touch_endpoint(vault=Depends(unlocked)):
    return {'active': True}

@app.get('/api/status')
def status_endpoint(request: Request):
    vault = request.app.state.vault
    vault.expire()
    auth = request.headers.get('authorization', '').removeprefix('Bearer ')
    authorized = bool(vault.token and auth and __import__('secrets').compare_digest(auth, vault.token))
    docs = vault.list('document') if authorized else []
    return {'initialized': vault.initialized, 'unlocked': authorized, 'auto_lock_minutes': vault.auto_lock_minutes,
            'recovery_configured': vault.recovery_configured,
            'backend_bind': '127.0.0.1:8000', 'outbound_policy': 'Fixed loopback Ollama only; STT local_files_only. No telemetry or external HTTP routes.',
            'external_requests': 0, 'blocked_external_connections': network.blocked_connections, 'socket_guard': network.installed, 'local_model_requests': llm.local_requests, 'llm_model': llm.MODEL,
            'embedding_model': llm.EMBED_MODEL, 'whisper_model': os.getenv('WHISPER_MODEL', 'small'),
            'documents': len(docs) if authorized else None, 'chunks': len(vault.index) if authorized else None}

@app.post('/api/structure', response_model=StructureResult)
async def structure_endpoint(body: StructureInput, vault=Depends(unlocked)):
    token = vault.token
    result = await structure(body.text)
    vault.authorize(token, touch=False)
    return result

app.include_router(records.router)
app.include_router(library.router)
app.include_router(demo.router)
app.include_router(voice.router)

if __name__ == '__main__':
    import logging
    import uvicorn
    # Access logs and exception logging are disabled to avoid accidental sensitive data.
    logging.getLogger('uvicorn.error').disabled = True
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000, access_log=False, log_config=None)
