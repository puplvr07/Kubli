"""Multilingual local STT. The app is forbidden from downloading model files."""
import os
from io import BytesIO
from threading import Lock
from fastapi import HTTPException

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
_model = None
_mutex = Lock()


def decode_local_audio(content: bytes):
    """Decode in-memory containers; native FFmpeg cannot open network protocols."""
    import av
    import numpy as np
    av.logging.set_level(av.logging.PANIC)
    try:
        arrays = []
        samples = 0
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        options = {'protocol_whitelist': 'pipe,data',
                   'format_whitelist': 'wav,flac,ogg,mp3,aac,matroska,webm,mov,mp4,m4a,3gp,3g2,mj2'}
        with av.open(BytesIO(content), mode='r', options=options) as container:
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    array = converted.to_ndarray().reshape(-1)
                    samples += array.size
                    if samples > 120 * 16000:
                        raise HTTPException(422, 'Record at most two minutes of audio at a time.')
                    arrays.append(array)
            for converted in resampler.resample(None):
                arrays.append(converted.to_ndarray().reshape(-1))
        if not arrays:
            raise ValueError('empty audio')
        return np.concatenate(arrays).astype(np.float32) / 32768.0
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, 'Unsupported or invalid audio. Record directly in WardNote or use a local WAV, FLAC, OGG, MP3, WebM or MP4 audio file.') from None


def transcribe_audio(content: bytes) -> dict:
    global _model
    with _mutex:
        if _model is None:
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from faster_whisper import WhisperModel
            model = os.getenv('WHISPER_MODEL_PATH') or os.getenv('WHISPER_MODEL', 'small')
            try:
                _model = WhisperModel(model, device='cpu', compute_type='int8', cpu_threads=2, num_workers=1,
                                      local_files_only=True, download_root=os.getenv('WHISPER_CACHE_DIR'))
            except Exception:
                raise HTTPException(503, 'Whisper model is not available locally. Before going offline run: python scripts/download_whisper.py --model small (from backend). Or set WHISPER_MODEL_PATH to a downloaded faster-whisper model directory.') from None
        try:
            segments, info = _model.transcribe(decode_local_audio(content), language=None, beam_size=3, vad_filter=True)
            text = ' '.join(segment.text.strip() for segment in segments).strip()
            if not text:
                raise HTTPException(422, 'No speech was detected. Try again in a quieter place or type the encounter.')
            return {'text': text, 'language': info.language, 'notice': 'Review and correct the transcript before structuring. Multilingual recognition, including Taglish, can be inaccurate.'}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, 'Audio could not be transcribed locally. Try a shorter recording or type the encounter.') from None
