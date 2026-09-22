"""Validate compare fixture manifest coverage and on-disk media."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

VALID_VERTICALS = frozenset({"call_center", "sales", "podcast", "interview"})
VALID_MEDIA_TYPES = frozenset({"audio", "video"})
REQUIRED_FIELDS = ("file", "call_date", "agent_id", "customer_id", "queue", "vertical", "media_type")
MAX_PER_VERTICAL_MEDIA = 2


def load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    return json.loads(manifest_path.read_text())


def validate_manifest(entries: list[dict[str, Any]], fixtures_dir: Path, *, require_files: bool = True) -> list[str]:
    errors: list[str] = []

    if not entries:
        errors.append("manifest is empty")
        return errors

    seen_files: set[str] = set()
    coverage: Counter[tuple[str, str]] = Counter()

    for idx, entry in enumerate(entries):
        label = f"entry[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: expected object")
            continue

        for field in REQUIRED_FIELDS:
            if field not in entry or entry[field] in (None, ""):
                errors.append(f"{label}: missing {field}")

        filename = str(entry.get("file", ""))
        if filename in seen_files:
            errors.append(f"{label}: duplicate file {filename!r}")
        seen_files.add(filename)

        vertical = entry.get("vertical")
        media_type = entry.get("media_type")
        if vertical not in VALID_VERTICALS:
            errors.append(f"{label}: invalid vertical {vertical!r}")
        if media_type not in VALID_MEDIA_TYPES:
            errors.append(f"{label}: invalid media_type {media_type!r}")
        if vertical in VALID_VERTICALS and media_type in VALID_MEDIA_TYPES:
            coverage[(vertical, media_type)] += 1

        if require_files and filename:
            path = fixtures_dir / filename
            if not path.is_file():
                errors.append(f"{label}: missing file {filename}")

    for vertical in sorted(VALID_VERTICALS):
        for media_type in sorted(VALID_MEDIA_TYPES):
            count = coverage[(vertical, media_type)]
            if count < 1:
                errors.append(f"coverage: {vertical} missing {media_type} fixture")
            if count > MAX_PER_VERTICAL_MEDIA:
                errors.append(
                    f"coverage: {vertical} has {count} {media_type} fixtures (max {MAX_PER_VERTICAL_MEDIA})"
                )

    return errors
