"""Start the loopback-only WardNote backend from Windows or Linux."""

import logging
import os
from pathlib import Path

import uvicorn


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "WHISPER_MODEL_PATH",
    str(REPOSITORY_ROOT / ".wardnote" / "models" / "whisper-small"),
)

from app.main import app  # noqa: E402  (environment must be configured first)


if __name__ == "__main__":
    # Avoid writing patient content through server access or exception logs.
    logging.getLogger("uvicorn.error").disabled = True
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False, log_config=None)
