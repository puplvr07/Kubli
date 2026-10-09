import os
import numpy as np
import threading
from fastapi import HTTPException
from app.services import llm

_model = None
_mutex = threading.Lock()

def decode_local_audio(content: bytes):
    try:
        import librosa
        import soundfile as sf
        import io
        data, sr = sf.read(io.BytesIO(content))
        if sr != 16000:
            import librosa
            data = librosa.resample(data, orig_sr=sr, target_sr=16000)
        return data.astype(np.float32)
    except Exception:
        raise HTTPException(422, "Unsupported or invalid audio. Record directly in WardNote or use a local WAV, FLAC, OGG, MP3, WebM or MP4 audio file.")

def transcribe_audio(content: bytes) -> dict:
    global _model
    with _mutex:
        if _model is None:
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from faster_whisper import WhisperModel
            model_path = os.getenv("WHISPER_MODEL_PATH") or os.getenv("WHISPER_MODEL", "small")
            try:
                # Try int8 first for speed
                _model = WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=2, num_workers=1, local_files_only=True, download_root=os.getenv("WHISPER_CACHE_DIR"))
            except Exception as e:
                print(f"Whisper int8 load failed: {e}. Trying float32...")
                try:
                    _model = WhisperModel(model_path, device="cpu", compute_type="float32", cpu_threads=2, num_workers=1, local_files_only=True, download_root=os.getenv("WHISPER_CACHE_DIR"))
                except Exception as e2:
                    print(f"Whisper float32 load failed: {e2}")
                    raise HTTPException(503, f"Whisper model failed to load: {str(e2)}") from None
        try:
            segments, info = _model.transcribe(decode_local_audio(content), language=None, beam_size=3, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if not text:
                raise HTTPException(422, "No speech was detected. Try again in a quieter place or type the encounter.")
            return {"text": text, "language": info.language, "notice": "Review and correct the transcript before structuring. Multilingual recognition, including Taglish, can be inaccurate."}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Audio could not be transcribed locally. Try a shorter recording or type the encounter.") from None