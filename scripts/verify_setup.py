#!/usr/bin/env python3
"""Verify local schema setup."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backends" / "pixeltable"))

import schema  # noqa: F401
import pixeltable as pxt


def main() -> int:
    tables = pxt.list_tables()
    required = {
        "call_center/calls",
        "call_center/transcript_segments",
        "call_center/coaching_comments",
    }
    missing = required - set(tables)
    if missing:
        print(f"Missing tables: {sorted(missing)}")
        return 1

    calls = pxt.get_table("call_center.calls")
    segments = pxt.get_table("call_center.transcript_segments")
    comments = pxt.get_table("call_center.coaching_comments")

    call_cols = set(calls.columns())
    expected = {
        "video",
        "media_type",
        "source_audio",
        "diarized",
        "segments",
        "transcript_text",
        "summary_raw",
        "action_items_raw",
        "sentiment_raw",
        "category_raw",
        "qa_raw",
        "summary",
        "action_items",
        "sentiment",
        "category",
        "qa_scorecard",
        "handle_time_sec",
        "pipeline_status",
        "original_filename",
    }
    if not expected.issubset(call_cols):
        print(f"Missing call columns: {sorted(expected - call_cols)}")
        return 1

    segment_cols = set(segments.columns())
    if not {"speaker", "start_sec", "end_sec", "text"}.issubset(segment_cols):
        print(
            "Missing segment columns: "
            f"{sorted({'speaker', 'start_sec', 'end_sec', 'text'} - segment_cols)}"
        )
        return 1

    print(f"OK: call_center.calls columns = {calls.columns()}")
    print(f"OK: call_center.transcript_segments columns = {segments.columns()}")
    print(f"OK: call_center.coaching_comments columns = {comments.columns()}")
    print("Schema verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
