#!/usr/bin/env python3
"""Inner implementation for demo_recompute (runs inside Pixeltable backend venv)."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

PXT_DIR = Path(__file__).resolve().parent.parent / "backends" / "pixeltable"
ROOT = PXT_DIR.parent.parent
sys.path.insert(0, str(PXT_DIR))
os.chdir(PXT_DIR)
os.environ.setdefault("PIXELTABLE_HOME", str(ROOT / "data" / "pixeltable"))

import config
import pixeltable as pxt
STATE_FILE = ROOT / ".compare-state.json"
REF_API = os.getenv("REF_API", "http://127.0.0.1:8001")


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


def _records(rows) -> list[dict]:
    if rows is None or len(rows) == 0:
        return []
    return rows.to_dict("records") if hasattr(rows, "to_dict") else list(rows)


def main() -> int:
    os.environ.setdefault("PIXELTABLE_HOME", str(ROOT / "data" / "pixeltable"))
    if not STATE_FILE.is_file():
        print(f"Missing {STATE_FILE}. Run: ./scripts/run_compare.sh seed")
        return 1

    state = json.loads(STATE_FILE.read_text())
    fixture_name = "billing-inquiry-speech.wav"
    ids = state.get(fixture_name)
    if not ids:
        print(f"Missing fixture {fixture_name} in compare state")
        return 1

    call_id = uuid.UUID(ids["pxt_id"])
    calls = pxt.get_table(f"{config.APP_NAMESPACE}.calls")

    print(f"\n=== incremental recompute ({fixture_name}) ===")
    before_rows = (
        calls.where(calls.uuid == call_id)
        .select(
            calls.pipeline_status,
            calls.diarized,
            calls.segments,
            calls.transcript_text,
            calls.summary,
        )
        .collect()
    )
    if before_rows is None or len(before_rows) == 0:
        print("Pixeltable call not found — seed compare data first")
        return 1

    before = _records(before_rows)[0]
    if before.get("pipeline_status") != "completed":
        print(f"Call not completed (status={before.get('pipeline_status')}) — wait for pipeline")
        return 1

    calls.recompute_columns("summary", where=calls.uuid == call_id, cascade=False)

    after_rows = (
        calls.where(calls.uuid == call_id)
        .select(
            calls.diarized,
            calls.segments,
            calls.transcript_text,
            calls.summary,
        )
        .collect()
    )
    after = _records(after_rows)[0]

    all_ok = True
    all_ok = check("diarized unchanged after summary recompute", before["diarized"] == after["diarized"]) and all_ok
    all_ok = check("segments unchanged after summary recompute", before["segments"] == after["segments"]) and all_ok
    all_ok = check(
        "transcript_text unchanged after summary recompute",
        before["transcript_text"] == after["transcript_text"],
    ) and all_ok
    all_ok = check("summary still populated", bool(after.get("summary"))) and all_ok

    print("\n=== reference contrast ===")
    try:
        import httpx

        with httpx.Client(timeout=30.0) as client:
            ref = client.get(f"{REF_API}/api/calls/{ids['ref_id']}").json()
            seg_count = len(ref.get("segments") or [])
            check(
                "reference call available for contrast",
                ref.get("status") == "completed",
                f"segments={seg_count}",
            )
    except Exception as exc:
        check("reference call available for contrast", False, str(exc))
        all_ok = False

    print(
        "\nReference `process_call` deletes and re-inserts all segments "
        "(worker/tasks/process_call.py), orphaning comment anchors."
    )
    print("Pixeltable `recompute_columns('summary', cascade=False)` leaves transcription intact.")

    print("\n" + ("Incremental recompute demo passed." if all_ok else "Incremental recompute demo failed."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
