"""Extract MP3 audio from a video with ffmpeg, as Pixeltable's extract_audio does."""

from __future__ import annotations

import subprocess
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


def is_video_extension(ext: str) -> bool:
    return ext.lower() in VIDEO_EXTENSIONS


def extract_audio_from_video(video_path: Path, output_path: Path) -> None:
    """Writes a temporary file and renames it on success, so a failed or killed run never leaves a partial
    output_path that a retry would take for finished audio."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_suffix(".partial" + output_path.suffix)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "2",
        str(partial),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg timed out extracting audio") from exc
    if result.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "ffmpeg did not produce output audio file")
    partial.replace(output_path)
