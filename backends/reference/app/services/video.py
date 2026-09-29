"""Extract MP3 audio from a video with ffmpeg, as Pixeltable's extract_audio does."""

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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg timed out extracting audio") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed to extract audio")
    if not output_path.is_file():
        raise RuntimeError("ffmpeg did not produce output audio file")
