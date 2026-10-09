"""Tests for compare fixture manifest coverage."""

from pathlib import Path

from call_center_api.fixture_manifest import load_manifest, validate_manifest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "compare" / "fixtures"
MANIFEST = FIXTURES / "manifest.json"


def test_manifest_structure_and_coverage() -> None:
    entries = load_manifest(MANIFEST)
    errors = validate_manifest(entries, FIXTURES, require_files=False)
    assert errors == [], "\n".join(errors)


def test_manifest_has_ten_fixtures() -> None:
    entries = load_manifest(MANIFEST)
    assert len(entries) == 10


def test_each_vertical_has_audio_and_video() -> None:
    entries = load_manifest(MANIFEST)
    by_vertical: dict[str, set[str]] = {}
    for entry in entries:
        by_vertical.setdefault(entry["vertical"], set()).add(entry["media_type"])
    for vertical in ("call_center", "sales", "podcast", "interview"):
        assert "audio" in by_vertical.get(vertical, set())
        assert "video" in by_vertical.get(vertical, set())
