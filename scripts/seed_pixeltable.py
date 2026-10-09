#!/usr/bin/env python3
"""Add the committed six-second teaching fixture to the Pixeltable lesson, without resetting data."""

import json
import os
from pathlib import Path

from lib.client import FIXTURES, Api, load_manifest

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "lesson" / "fixture.json"


def main() -> int:
    api = Api("pixeltable", os.getenv("PXT_API", "http://127.0.0.1:8002"))
    try:
        if STATE_FILE.is_file():
            previous = json.loads(STATE_FILE.read_text())
            call = api.detail(previous["call_id"])
            if call is not None:
                print(f"Lesson fixture already exists: {call['id']} ({call['status']}); no duplicate uploaded.")
                return 0 if call["status"] == "completed" else 1
        health = api.health()
        if health["status"] != "ok" or health.get("enrichment_profile") != "core":
            raise RuntimeError("Start the core lesson before adding its fixture")
        entry = next(entry for entry in load_manifest() if entry["file"] == "billing-inquiry-speech.wav")
        call_id = api.upload(FIXTURES / entry["file"], entry)
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"call_id": call_id, "file": entry["file"]}, indent=2) + "\n")
        call = api.wait(call_id).call
        print(f"{entry['file']}: {call['status']} ({call_id}). Open the lesson UI to inspect the evidence.")
        return 0 if call["status"] == "completed" else 1
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
