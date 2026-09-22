import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
load_dotenv(override=True)

_home = Path(os.getenv("PIXELTABLE_HOME", str(_REPO_ROOT / "data" / "pixeltable")))
if not _home.is_absolute():
    _home = (_REPO_ROOT / _home).resolve()
os.environ["PIXELTABLE_HOME"] = str(_home)

APP_NAMESPACE = "call_center"

WHISPERX_MODEL = os.getenv("WHISPERX_MODEL", "base")
WHISPERX_DIARIZATION_MODEL = os.getenv(
    "WHISPERX_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)
HF_TOKEN = os.getenv("HF_TOKEN", "")
if HF_TOKEN:
    os.environ.setdefault("HF_TOKEN", HF_TOKEN)

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "all-mpnet-base-v2")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
if OLLAMA_HOST:
    os.environ.setdefault("OLLAMA_HOST", OLLAMA_HOST)

MAX_QUERY_LENGTH: int = int(os.getenv("MAX_QUERY_LENGTH", "10000"))
MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "100"))
UPLOAD_DIR = Path(
    os.getenv(
        "PXT_UPLOAD_DIR",
        str(Path(__file__).resolve().parents[2] / "data" / "pixeltable" / "uploads"),
    )
)

CORS_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:8000",
    ).split(",")
    if origin.strip()
]
