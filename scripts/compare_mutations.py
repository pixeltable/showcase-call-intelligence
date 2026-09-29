#!/usr/bin/env python3
"""Gate: comments and delete behave the same on both backends, down to the stores.

Uses a fresh upload per backend, so seeded fixture ids are untouched. Writes compare/reports/mutations.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from call_center_api.schemas import CallDetail, CommentOut  # noqa: E402
from lib.client import FIXTURES, Api, backends, load_manifest  # noqa: E402
from lib.contract import conforms  # noqa: E402
from lib.report import Checks, write_report  # noqa: E402

FIXTURE = "billing-inquiry-speech.wav"

# What each store still holds for a call, read from the store rather than through the API.
STORE_PROBES = {
    "reference": (
        ROOT / "backends" / "reference",
        """
import json, sys
from pathlib import Path
from sqlalchemy import text
from app.database import engine
cid = sys.argv[1]
with engine.connect() as c:
    q = lambda sql: c.execute(text(sql), {"id": cid}).scalar()
    row = c.execute(text("SELECT audio_path, video_path FROM calls WHERE id = :id"), {"id": cid}).first()
    out = {"calls": q("SELECT count(*) FROM calls WHERE id = :id"),
           "segments": q("SELECT count(*) FROM transcript_segments WHERE call_id = :id"),
           "comments": q("SELECT count(*) FROM coaching_comments WHERE call_id = :id")}
print(json.dumps(out))
""",
    ),
    "pixeltable": (
        ROOT / "backends" / "pixeltable",
        """
import json, sys, uuid
import pixeltable as pxt
cid = uuid.UUID(sys.argv[1])
t = {n: pxt.get_table(f"call_center.{n}") for n in ("calls", "transcript_segments", "coaching_comments")}
print(json.dumps({"calls": t["calls"].where(t["calls"].id == cid).count(),
                  "segments": t["transcript_segments"].where(t["transcript_segments"].id == cid).count(),
                  "comments": t["coaching_comments"].where(t["coaching_comments"].call_id == cid).count()}))
""",
    ),
}


def store_counts(backend: str, call_id: str) -> dict:
    cwd, script = STORE_PROBES[backend]
    out = subprocess.run(["uv", "run", "--quiet", "python", "-c", script, call_id], cwd=cwd, capture_output=True, text=True)
    lines = [line for line in out.stdout.splitlines() if line.startswith("{")]
    if out.returncode != 0 or not lines:
        raise RuntimeError(f"{backend} store probe failed: {out.stderr[-500:]}")
    return json.loads(lines[-1])


def upload_files(call_id: str) -> list[str]:
    return [str(p) for p in (ROOT / "data").glob(f"*/uploads/{call_id}.*")]


def exercise(c: Checks, api: Api, entry: dict) -> dict:
    call_id = api.upload(FIXTURES / FIXTURE, entry, agent_suffix="mutation-test")
    c.check(f"{api.name} detail while processing matches CallDetail", *conforms(CallDetail, api.detail(call_id)))
    call = api.wait(call_id).call
    c.check(f"{api.name} upload completed", call["status"] == "completed", call.get("error_message") or "")
    seg = call["segments"][0]
    anchored = api.comment(call_id, segment_id=seg["id"], start_sec=seg["start_sec"], author="qa-reviewer", text="segment note")
    loose = api.comment(call_id, segment_id=None, start_sec=0.0, author="qa-reviewer", text="call note")
    c.check(f"{api.name} anchored comment keeps its segment", anchored["segment_id"] == seg["id"])
    c.check(f"{api.name} comment matches CommentOut", *conforms(CommentOut, anchored))
    c.check(f"{api.name} call-level comment has no segment", loose["segment_id"] is None)
    for bad_segment in (f"{call_id}:999", str(uuid.uuid4())):
        try:
            api.comment(call_id, segment_id=bad_segment, start_sec=0.0, author="qa", text="x")
            c.check(f"{api.name} rejects foreign segment {bad_segment[-4:]}", False)
        except RuntimeError as exc:
            c.check(f"{api.name} rejects foreign segment {bad_segment[-4:]}", "400" in str(exc) or "422" in str(exc), str(exc)[:80])
    try:
        api.comment(str(uuid.uuid4()), segment_id=None, start_sec=0.0, author="qa", text="x")
        c.check(f"{api.name} comment on unknown call is 404", False)
    except RuntimeError as exc:
        c.check(f"{api.name} comment on unknown call is 404", "404" in str(exc), str(exc)[:80])

    detail = api.detail(call_id)
    c.check(f"{api.name} detail lists 2 comments", len(detail["comments"]) == 2)
    c.check(f"{api.name} comments route lists 2", len(api.comments(call_id)) == 2)
    c.check(f"{api.name} comments match CommentOut", *conforms(list[CommentOut], api.comments(call_id)))
    c.check(f"{api.name} search finds the call", any(h["call_id"] == call_id for h in api.search("billing")))

    before = store_counts(api.name, call_id)
    c.check(f"{api.name} store holds call, segments, comments", before["calls"] == 1 and before["segments"] > 0 and before["comments"] == 2, json.dumps(before))
    files_before = upload_files(call_id)
    c.check(f"{api.name} upload file on disk", len(files_before) > 0)

    c.check(f"{api.name} DELETE is 204", api.delete(call_id) == 204)
    c.check(f"{api.name} GET after delete is 404", api.detail(call_id) is None)
    c.check(f"{api.name} second DELETE is 404", api.delete(call_id) == 404)
    c.check(f"{api.name} roster drops the call", all(r["id"] != call_id for r in api.list_calls(limit=200)))
    c.check(f"{api.name} search drops the call", all(h["call_id"] != call_id for h in api.search("billing")))
    after = store_counts(api.name, call_id)
    c.check(f"{api.name} store holds nothing for the call", after == {"calls": 0, "segments": 0, "comments": 0}, json.dumps(after))
    c.check(f"{api.name} upload files removed", upload_files(call_id) == [], str(upload_files(call_id)))
    return {"call_id": call_id, "store_before": before, "store_after": after, "files_before": files_before}


def main() -> int:
    entry = next(e for e in load_manifest() if e["file"] == FIXTURE)
    c = Checks("mutations")
    for api in backends():
        c.record(api.name, exercise(c, api, entry))
    write_report("mutations", c.report())
    return c.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
