#!/usr/bin/env python3
"""Generate synthetic two-speaker WAV fixtures for compare seeding."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "compare" / "fixtures"
SAMPLE_RATE = 16000

FIXTURE_SCRIPTS: dict[str, list[tuple[str, str]]] = {
    "sales-discovery.wav": [
        (
            "AGENT",
            "Hi, thanks for taking my call. I'm Alex from CloudMetrics. "
            "Can you tell me how your team handles reporting today?",
        ),
        (
            "CUSTOMER",
            "We're mostly using spreadsheets. It's slow and our finance team is frustrated.",
        ),
        (
            "AGENT",
            "That makes sense. A lot of teams outgrow spreadsheets around your size. "
            "Would a live demo next Tuesday help you compare options?",
        ),
        (
            "CUSTOMER",
            "Maybe. Pricing is a concern, and we'd need security review before any pilot.",
        ),
        (
            "AGENT",
            "Understood. I'll send a one-page overview and schedule a follow-up with your finance lead.",
        ),
    ],
    "interview-behavioral.wav": [
        (
            "AGENT",
            "Thanks for joining today. Can you walk me through a time you handled a tight deadline?",
        ),
        (
            "CUSTOMER",
            "Last quarter we had a production incident. I coordinated the rollback and kept stakeholders updated.",
        ),
        (
            "AGENT",
            "What was the hardest part of that situation?",
        ),
        (
            "CUSTOMER",
            "Balancing speed with communication. I wrote a short postmortem and proposed two process changes.",
        ),
        (
            "AGENT",
            "Great. We'll discuss next steps with the panel and get back to you by Friday.",
        ),
    ],
}


def _require_tools() -> None:
    if shutil.which("say") is None:
        raise RuntimeError("macOS 'say' command not found. Generate on Darwin or commit pre-built WAVs.")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH.")


def _say_to_wav(text: str, voice: str, dest: Path) -> None:
    aiff = dest.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(aiff),
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
    aiff.unlink(missing_ok=True)


def _concat_wavs(parts: list[Path], dest: Path) -> None:
    list_file = dest.with_suffix(".txt")
    list_file.write_text("".join(f"file '{part.resolve()}'\n" for part in parts))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
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
    list_file.unlink(missing_ok=True)


def generate_fixture(filename: str, lines: list[tuple[str, str]], *, force: bool) -> Path:
    dest = FIXTURES / filename
    if dest.is_file() and not force:
        print(f"  OK {filename} (exists)")
        return dest

    agent_voice = "Samantha"
    customer_voice = "Daniel"
    FIXTURES.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fixture-audio-") as tmp:
        tmp_dir = Path(tmp)
        parts: list[Path] = []
        for idx, (_speaker, text) in enumerate(lines):
            part = tmp_dir / f"{idx:02d}.wav"
            voice = agent_voice if idx % 2 == 0 else customer_voice
            _say_to_wav(text, voice, part)
            parts.append(part)
        _concat_wavs(parts, dest)

    print(f"  OK {filename}")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic compare fixture WAV files.")
    parser.add_argument("--force", action="store_true", help="Regenerate even if output exists")
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(FIXTURE_SCRIPTS.keys()),
        help="Generate a single fixture",
    )
    args = parser.parse_args()

    targets = args.only or sorted(FIXTURE_SCRIPTS.keys())
    needs_tools = args.force or any(not (FIXTURES / name).is_file() for name in targets)
    if needs_tools:
        try:
            _require_tools()
        except RuntimeError as exc:
            print(exc)
            return 1

    for filename in targets:
        generate_fixture(filename, FIXTURE_SCRIPTS[filename], force=args.force)

    print("Synthetic fixture audio ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
