import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.services.video import is_video_extension
from call_center_api.constants import ALLOWED_UPLOAD_EXTENSIONS


def get_upload_dir() -> Path:
    path = settings.upload_dir_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(file: UploadFile, call_id: uuid.UUID) -> tuple[str, str, str | None, str]:
    """Save upload and return (audio_path, original_filename, video_path, media_type).

    For video, audio_path is where the worker writes the extracted MP3; it does not exist yet.
    """
    ext = Path(file.filename or "audio.wav").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")

    file.file.seek(0, 2)
    size_bytes = file.file.tell()
    file.file.seek(0)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ValueError(f"File exceeds {settings.max_upload_mb}MB limit")

    upload_dir = get_upload_dir()
    original_filename = file.filename or f"recording{ext}"
    dest = upload_dir / f"{call_id}{ext}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    if is_video_extension(ext):
        audio_dest = upload_dir / f"{call_id}.mp3"
        return str(audio_dest.resolve()), original_filename, str(dest.resolve()), "video"
    return str(dest.resolve()), original_filename, None, "audio"


def resolve_upload_file(path_str: str | None) -> Path | None:
    """Return a file under the upload directory, or None if the path escapes it."""
    if not path_str:
        return None
    root = get_upload_dir().resolve()
    try:
        resolved = Path(path_str).resolve()
    except OSError:
        return None
    if not resolved.is_file() or not resolved.is_relative_to(root):
        return None
    return resolved


def safe_download_name(name: str | None, fallback: str = "download") -> str:
    """Basename safe for Content-Disposition (no paths or header breaks)."""
    raw = Path(name or fallback).name
    cleaned = "".join(ch for ch in raw if ch.isprintable() and ch not in {'"', "\\", "/", "\r", "\n"})
    return cleaned or Path(fallback).name or "download"


def delete_upload_files(audio_path: str, video_path: str | None = None) -> None:
    for path_str in (audio_path, video_path):
        path = resolve_upload_file(path_str)
        if path is not None:
            path.unlink()
