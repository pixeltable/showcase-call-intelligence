"""Add, change, and selectively recompute one field on the dedicated lesson's existing call.

Run `./scripts/run_pixeltable.sh extend` after `seed`. No model calls are needed: a small business
rule uses the stored transcript. The exercise verifies preserved source/summary/comment evidence
and removes only its temporary field and probe comment, leaving the lesson ready to run again.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pixeltable as pxt
from pixeltable.functions.string import contains

ROOT = Path(__file__).resolve().parents[1]
FIELD = "lesson_needs_billing_review"


def exercise(calls: pxt.Table, comments: pxt.Table, call_id: uuid.UUID) -> dict:
    if FIELD in calls.columns():
        raise ValueError(f"{FIELD} already exists; refusing to replace it")
    source = calls.where(calls.id == call_id).select(calls.transcript, calls.segments, calls.summary).collect()
    if (len(source) != 1 or not source[0]["segments"] or not source[0]["summary"]
            or "billing" not in (source[0]["transcript"] or "").lower()):
        raise ValueError("Use the completed billing fixture for this exercise")
    before = source[0]
    segment_id = uuid.uuid5(call_id, "0")
    probe = comments.insert([{"call_id": call_id, "segment_id": str(segment_id),
                             "start_sec": before["segments"][0]["start_sec"], "author": "lesson",
                             "comment": "Preserve this evidence anchor", "created_at": datetime.now(timezone.utc)}],
                            return_rows=True).rows[0]
    added = False
    try:
        # Adding a computed column backfills it from the existing transcript.
        calls.add_computed_column(**{FIELD: contains(calls.transcript, "__no_matching_topic__", case=False)})
        added = True
        initial = calls.where(calls.id == call_id).select(calls[FIELD]).collect()[0][FIELD]
        # Updating an expression can leave stored values intact until explicit recompute.
        calls.alter_computed_column(**{FIELD: contains(calls.transcript, "billing", case=False)}, recompute=False)
        unchanged = calls.where(calls.id == call_id).select(calls[FIELD]).collect()[0][FIELD]
        calls.recompute_columns(FIELD)
        final = calls.where(calls.id == call_id).select(calls[FIELD]).collect()[0][FIELD]
        after = calls.where(calls.id == call_id).select(calls.transcript, calls.segments, calls.summary).collect()[0]
        anchor = comments.where(comments.id == probe["id"]).select(comments.segment_id).collect()[0]["segment_id"]
        result = {"initial": initial, "before_recompute": unchanged, "after_recompute": final,
                  "transcript_summary_segments_unchanged": before == after,
                  "comment_still_anchored": anchor == str(segment_id)}
        if result != {"initial": False, "before_recompute": False, "after_recompute": True,
                      "transcript_summary_segments_unchanged": True, "comment_still_anchored": True}:
            raise AssertionError(f"Exercise invariant failed: {result}")
        return result
    finally:
        if added:
            calls.drop_column(FIELD)
        comments.delete(where=comments.id == probe["id"])


def main() -> int:
    expected_home = ROOT / "data" / "lesson" / "pixeltable"
    if Path(os.getenv("PIXELTABLE_HOME", "")).resolve() != expected_home.resolve():
        raise SystemExit("Use run_pixeltable.sh extend; this exercise is confined to its dedicated lesson catalog")
    state = json.loads((ROOT / "data" / "lesson" / "fixture.json").read_text())
    result = exercise(pxt.get_table("first_lesson/calls"), pxt.get_table("first_lesson/coaching_comments"),
                      uuid.UUID(state["call_id"]))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
