#!/usr/bin/env python3
"""Download compare fixture media listed in compare/fixtures/sources.json."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "compare" / "fixtures"
SOURCES = FIXTURES / "sources.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_entry(client: httpx.Client, entry: dict, *, force: bool) -> bool:
    filename = entry["filename"]
    dest = FIXTURES / filename
    expected = entry["sha256"]

    if dest.is_file() and not force:
        actual = sha256_file(dest)
        if actual == expected:
            print(f"  OK {filename} (cached)")
            return True
        print(f"  MISMATCH {filename}: expected {expected}, got {actual}")

    print(f"  Downloading {filename}…")
    resp = client.get(entry["url"])
    resp.raise_for_status()
    dest.write_bytes(resp.content)

    actual = sha256_file(dest)
    if actual != expected:
        print(f"  FAIL {filename}: sha256 {actual} != {expected}")
        return False

    size = entry.get("size_bytes")
    if size is not None and dest.stat().st_size != size:
        print(f"  WARN {filename}: size {dest.stat().st_size} != expected {size}")

    print(f"  OK {filename}")
    return True


def verify_source_files(entries: list[dict]) -> list[str]:
    """Check downloads from sources.json only. Derived copies are prepared later."""
    missing = []
    for entry in entries:
        path = FIXTURES / entry["filename"]
        if not path.is_file():
            missing.append(entry["filename"])
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Download compare fixture media.")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached hash matches")
    args = parser.parse_args()

    if not SOURCES.is_file():
        print(f"Missing {SOURCES}")
        return 1

    FIXTURES.mkdir(parents=True, exist_ok=True)
    entries = json.loads(SOURCES.read_text())
    ok = True

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        for entry in entries:
            if not fetch_entry(client, entry, force=args.force):
                ok = False

    missing = verify_source_files(entries)
    if missing:
        print("Missing sources.json downloads:")
        for name in missing:
            print(f"  - {name}")
        ok = False

    if ok:
        print("All fixture media ready.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
