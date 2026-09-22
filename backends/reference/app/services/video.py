"""Extract audio from video uploads via ffmpeg (MP3 — matches Pixeltable extract_audio)."""

from __future__ import annotations

import subprocess
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}


def is_video_extension(ext: str) -> bool:
    return ext.lower() in VIDEO_EXTENSIONS


def extract_audio_from_video(video_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed to extract audio")
    if not output_path.is_file():
        raise RuntimeError("ffmpeg did not produce output audio file")
