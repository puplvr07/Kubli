from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from app.dependencies import unlocked
from app.services.stt import transcribe_audio

router = APIRouter(prefix='/api')

@router.post('/transcribe')
async def transcribe(vault=Depends(unlocked), audio: UploadFile = File(...)):
    token = vault.token
    content = await audio.read(20 * 1024 * 1024 + 1)
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Audio must be nonempty and smaller than 20 MB. Record at most two minutes.')
    result = await run_in_threadpool(transcribe_audio, content)
    vault.authorize(token, touch=False)
    return result
