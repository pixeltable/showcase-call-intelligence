"""Saved example data stays tied to the actual recorded speech, with no invented model success."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_example_transcript_and_media_match_recorded_evidence():
    recorded = json.loads((ROOT / "docs/validation/2026-10-09.json").read_text())
    example = json.loads((ROOT / "frontend/src/examples/billing.json").read_text())
    provenance = json.loads((ROOT / "frontend/public/examples/provenance.json").read_text())
    assert example["segments"] == recorded["first_attempt"]["segments"]
    assert hashlib.sha256((ROOT / "frontend/public/examples/billing-inquiry-speech.wav").read_bytes()).hexdigest() == recorded["fixture"]["sha256"]
    assert provenance["summary"]["live_model_result"] is False
    assert "authored" in provenance["summary"]["source"]
    assert "keyword" in provenance["search"]
    assert "Browser-local" in provenance["comments"]
    assert example["sentiment"] is None and example["qa_scorecard"] is None
