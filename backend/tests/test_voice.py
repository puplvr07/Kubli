from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.services import stt


def test_whisper_never_downloads_and_autodetects(monkeypatch):
    import faster_whisper
    calls = {}
    class FakeWhisper:
        def __init__(self, model, **kwargs): calls.update(kwargs)
        def transcribe(self, content, **kwargs):
            calls.update(kwargs)
            return iter([SimpleNamespace(text='May lagnat po for two days.')]), SimpleNamespace(language='tl')
    monkeypatch.setattr(stt, 'decode_local_audio', lambda content: __import__('numpy').zeros(16000, dtype='float32'))
    monkeypatch.setattr(faster_whisper, 'WhisperModel', FakeWhisper)
    monkeypatch.setattr(stt, '_model', None)
    result = stt.transcribe_audio(b'local audio')
    assert result['language'] == 'tl'
    assert calls['local_files_only'] is True
    assert calls['compute_type'] == 'int8' and calls['device'] == 'cpu'
    assert calls['language'] is None


def test_missing_whisper_clean_setup_message(monkeypatch):
    import faster_whisper
    def missing(*args, **kwargs): raise FileNotFoundError('not cached')
    monkeypatch.setattr(faster_whisper, 'WhisperModel', missing)
    monkeypatch.setattr(stt, '_model', None)
    with pytest.raises(HTTPException) as error: stt.transcribe_audio(b'audio')
    assert error.value.status_code == 503 and 'download_whisper.py' in error.value.detail


def test_local_audio_decoder_accepts_real_wav():
    import wave
    from io import BytesIO
    output = BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\x00\x00' * 16000)
    samples = stt.decode_local_audio(output.getvalue())
    assert samples.shape == (16000,) and str(samples.dtype) == 'float32'


def test_audio_playlist_cannot_fetch_a_source():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(1); self.send_response(200); self.end_headers()
        def log_message(self, *args): pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    playlist = f'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10,\nhttp://127.0.0.1:{server.server_port}/segment.ts\n#EXT-X-ENDLIST\n'.encode()
    try:
        with pytest.raises(HTTPException) as error: stt.decode_local_audio(playlist)
        assert error.value.status_code == 422 and calls == []
    finally:
        server.shutdown(); server.server_close(); thread.join()
