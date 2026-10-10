#!/usr/bin/env python3
"""Add the committed six-second teaching fixture to the Pixeltable lesson, without resetting data."""

import json
import os
import uuid
from pathlib import Path

from lib.client import FIXTURES, Api, load_manifest

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "lesson" / "fixture.json"


def main() -> int:
    api = Api("pixeltable", os.getenv("PXT_API", "http://127.0.0.1:8002"))
    try:
        previous = None
        if STATE_FILE.is_file():
            previous = json.loads(STATE_FILE.read_text())
            if previous.get("call_id"):
                call = api.detail(previous["call_id"])
                if call is not None:
                    print(f"Lesson fixture already exists: {call['id']} ({call['status']}); no duplicate uploaded.")
                    return 0 if call["status"] == "completed" else 1
                previous = None  # An explicitly deleted call needs a new request identity.
        health = api.health()
        if health["status"] != "ok" or health.get("enrichment_profile") != "core":
            raise RuntimeError("Start the core lesson before adding its fixture")
        if previous and previous.get("request_key") and previous.get("metadata"):
            intent = previous
        else:
            entry = next(entry for entry in load_manifest() if entry["file"] == "billing-inquiry-speech.wav")
            intent = {"request_key": str(uuid.uuid4()), "metadata": entry, "file": entry["file"]}
            save_state(intent)  # Preserve the key and date before sending, including lost-response retries.
        entry = intent["metadata"]
        call_id = api.upload(FIXTURES / entry["file"], entry, idempotency_key=intent["request_key"])
        save_state({**intent, "call_id": call_id})
        call = api.wait(call_id).call
        print(f"{entry['file']}: {call['status']} ({call_id}). Open the lesson UI to inspect the evidence.")
        return 0 if call["status"] == "completed" else 1
    finally:
        api.close()


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    with temporary.open("w") as output:
        output.write(json.dumps(state, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(STATE_FILE)


if __name__ == "__main__":
    raise SystemExit(main())
