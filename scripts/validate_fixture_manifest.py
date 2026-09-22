#!/usr/bin/env python3
"""Validate compare fixture manifest structure, coverage, and on-disk media."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "compare" / "fixtures"
MANIFEST = FIXTURES / "manifest.json"

sys.path.insert(0, str(ROOT / "shared"))

from call_center_api.fixture_manifest import load_manifest, validate_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate compare/fixtures/manifest.json")
    parser.add_argument(
        "--skip-files",
        action="store_true",
        help="Validate manifest structure/coverage only (do not require media on disk)",
    )
    args = parser.parse_args()

    if not MANIFEST.is_file():
        print(f"Missing manifest: {MANIFEST}")
        return 1

    entries = load_manifest(MANIFEST)
    errors = validate_manifest(entries, FIXTURES, require_files=not args.skip_files)
    if errors:
        print("Manifest validation failed:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"Manifest OK ({len(entries)} fixtures, all vertical/media coverage satisfied).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
