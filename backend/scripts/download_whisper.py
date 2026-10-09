"""Explicit setup utility. NEVER invoked by the running application."""
import argparse
import os
import hashlib
from pathlib import Path

parser = argparse.ArgumentParser(description='Download local speech model BEFORE using WardNote offline. Requires internet; no patient data is involved.')
parser.add_argument('--model', default=os.getenv('WHISPER_MODEL', 'small'))
parser.add_argument('--output', default=str(Path(__file__).resolve().parents[2] / '.wardnote' / 'models' / 'whisper-small'))
args = parser.parse_args()
# Supported HTTPS fallback uses the configured Python/proxy CA trust, instead of native Xet transport.
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
from huggingface_hub import snapshot_download
snapshot_download(repo_id='Systran/faster-whisper-' + args.model, local_dir=args.output,
                  allow_patterns=['model.bin', 'config.json', 'tokenizer.json', 'vocabulary.*', 'preprocessor_config.json'])
metadata = Path(args.output) / '.cache/huggingface/download/model.bin.metadata'
expected = metadata.read_text().splitlines()[1]
if len(expected) != 64:
    raise RuntimeError('Model SHA-256 metadata is unavailable; do not use unverified weights.')
with (Path(args.output) / 'model.bin').open('rb') as model_file:
    if hashlib.file_digest(model_file, 'sha256').hexdigest() != expected:
        raise RuntimeError('Model checksum mismatch; do not use these weights.')
print('Downloaded faster-whisper model locally. Set WHISPER_MODEL_PATH to:', args.output)
