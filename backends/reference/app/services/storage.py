import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.services.video import extract_audio_from_video, is_video_extension
from call_center_api.constants import ALLOWED_UPLOAD_EXTENSIONS


def get_upload_dir() -> Path:
    path = settings.upload_dir_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(file: UploadFile, call_id: uuid.UUID) -> tuple[str, str, str | None, str]:
    """Save upload and return (audio_path, original_filename, video_path, media_type)."""
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
    payload = file.file.read()

    if is_video_extension(ext):
        video_dest = upload_dir / f"{call_id}{ext}"
        video_dest.write_bytes(payload)
        audio_dest = upload_dir / f"{call_id}.mp3"
        extract_audio_from_video(video_dest, audio_dest)
        return str(audio_dest.resolve()), original_filename, str(video_dest.resolve()), "video"

    dest = upload_dir / f"{call_id}{ext}"
    dest.write_bytes(payload)
    return str(dest.resolve()), original_filename, None, "audio"


def delete_upload_files(audio_path: str, video_path: str | None = None) -> None:
    for path_str in (audio_path, video_path):
        if not path_str:
            continue
        path = Path(path_str)
        if path.is_file():
            path.unlink()
