#!/usr/bin/env python3
"""Materialize derived compare fixture media (extracts and copies)."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "compare" / "fixtures"
SAMPLE_RATE = 16000

DERIVED_COPIES: list[tuple[str, str]] = [
    ("pursuit-happiness-video.mp4", "sales-demo-video.mp4"),
    ("travel-briefing.mp4", "interview-session.mp4"),
]

DERIVED_EXTRACTS: list[tuple[str, str, float, float]] = [
    ("lex-fridman-excerpt.mp4", "podcast-excerpt-audio.wav", 0.0, 45.0),
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".sha256")


def read_sidecar(path: Path) -> str | None:
    sidecar = sidecar_path(path)
    if not sidecar.is_file():
        return None
    return sidecar.read_text().strip().split()[0]


def write_sidecar(path: Path) -> None:
    sidecar_path(path).write_text(f"{sha256_file(path)}  {path.name}\n")


def up_to_date(source: Path, dest: Path) -> bool:
    if not dest.is_file():
        return False
    expected = read_sidecar(dest)
    if expected is None:
        return False
    return sha256_file(dest) == expected and dest.stat().st_mtime >= source.stat().st_mtime


def copy_fixture(source_name: str, dest_name: str, *, force: bool) -> bool:
    source = FIXTURES / source_name
    dest = FIXTURES / dest_name
    if not source.is_file():
        print(f"  MISSING source {source_name}")
        return False
    if not force and up_to_date(source, dest):
        print(f"  OK {dest_name} (cached)")
        return True
    shutil.copy2(source, dest)
    write_sidecar(dest)
    print(f"  OK {dest_name}")
    return True


def extract_fixture(source_name: str, dest_name: str, start_sec: float, duration_sec: float, *, force: bool) -> bool:
    if shutil.which("ffmpeg") is None:
        print("  FAIL ffmpeg not found on PATH")
        return False

    source = FIXTURES / source_name
    dest = FIXTURES / dest_name
    if not source.is_file():
        print(f"  MISSING source {source_name}")
        return False
    if not force and up_to_date(source, dest):
        print(f"  OK {dest_name} (cached)")
        return True

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_sec),
            "-t",
            str(duration_sec),
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-sample_fmt",
            "s16",
            str(dest),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    write_sidecar(dest)
    print(f"  OK {dest_name}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare derived compare fixture media.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if cached sidecar matches")
    args = parser.parse_args()

    FIXTURES.mkdir(parents=True, exist_ok=True)
    ok = True

    print("Copying derived video fixtures…")
    for source_name, dest_name in DERIVED_COPIES:
        if not copy_fixture(source_name, dest_name, force=args.force):
            ok = False

    print("Extracting derived audio fixtures…")
    for source_name, dest_name, start_sec, duration_sec in DERIVED_EXTRACTS:
        if not extract_fixture(source_name, dest_name, start_sec, duration_sec, force=args.force):
            ok = False

    if ok:
        print("Derived fixture media ready.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
