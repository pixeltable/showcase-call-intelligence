"""Settings, read from the environment only.

The pxt daemon imports app.py and refuses to serve if the import changes its configuration, so this
module never loads .env itself. scripts/run_compare.sh exports .env before any `pxt` command.
"""

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

WHISPERX_MODEL = os.getenv("WHISPERX_MODEL", "base")
WHISPERX_DIARIZATION_MODEL = os.getenv("WHISPERX_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-mpnet-base-v2")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "100"))
UPLOAD_DIR = Path(os.getenv("PXT_UPLOAD_DIR", str(_REPO / "data" / "pixeltable" / "uploads"))).resolve()
# Media the API may serve: uploads, and the files Pixeltable computes (always $PIXELTABLE_HOME/media).
MEDIA_ROOTS = (UPLOAD_DIR, (Path(os.getenv("PIXELTABLE_HOME", "~/.pixeltable")).expanduser() / "media").resolve())
