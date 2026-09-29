#!/usr/bin/env python3
"""Gate: the two backends return the same product for the same seeded fixtures.

Structure must match exactly; LLM wording is allowed to differ (that is the model, not the backend).
Needs a seed (./scripts/run_compare.sh seed). Writes compare/reports/parity.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from call_center_api.schemas import CallDetail  # noqa: E402
from lib.client import backends, load_manifest  # noqa: E402
from lib.report import Checks, write_report  # noqa: E402

STATE_FILE = ROOT / ".compare-state.json"
CONTRACT_DETAIL_KEYS = set(CallDetail.model_fields)
QA_KEYS = {"empathy", "resolution", "compliance", "overall"}


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def words(text: str) -> list[str]:
    return [w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()]


def overlap(a: list[str], b: list[str]) -> float:
    """Word-level agreement of two transcripts: shared words over the longer one."""
    if not a and not b:
        return 1.0
    shared = sum(min(a.count(w), b.count(w)) for w in set(a))
    return shared / max(len(a), len(b))


def compare_call(c: Checks, name: str, entry: dict, ref: dict, pxt: dict) -> None:
    both = {"reference": ref, "pixeltable": pxt}
    for label, call in both.items():
        c.check(f"{name} {label} completed", call["status"] == "completed", call.get("error_message") or "")
        c.check(f"{name} {label} contract keys", CONTRACT_DETAIL_KEYS <= set(call), str(CONTRACT_DETAIL_KEYS - set(call)))
        c.check(f"{name} {label} vertical", call["vertical"] == entry["vertical"], call["vertical"])
        c.check(f"{name} {label} media_type", call["media_type"] == entry["media_type"], call["media_type"])
        c.check(f"{name} {label} qa keys", QA_KEYS <= set(call["qa_scorecard"] or {}))
        c.check(f"{name} {label} action_items is a list", isinstance(call["action_items"], list))
        c.check(f"{name} {label} category", bool(call["category"]))
        c.check(f"{name} {label} sentiment label", (call["sentiment"] or {}).get("label") in {"positive", "neutral", "negative", "unknown"})
    for key in ("agent_id", "customer_id", "queue", "has_video_source"):
        c.check(f"{name} same {key}", ref[key] == pxt[key], f"ref={ref[key]!r} pxt={pxt[key]!r}")
    c.check(f"{name} same call_date", instant(ref["call_date"]) == instant(pxt["call_date"]))

    # Same audio, same WhisperX parameters: the transcripts must agree. Segment boundaries can shift
    # by one when alignment differs across processes, so compare the words, not the cuts.
    ref_words = words(" ".join(s["text"] for s in ref["segments"]))
    pxt_words = words(" ".join(s["text"] for s in pxt["segments"]))
    agreement = overlap(ref_words, pxt_words)
    c.check(f"{name} transcript word agreement >= 0.9", agreement >= 0.9, f"{agreement:.3f}")
    c.check(f"{name} segment count within 1", abs(len(ref["segments"]) - len(pxt["segments"])) <= 1,
            f"ref={len(ref['segments'])} pxt={len(pxt['segments'])}")  # fmt: skip
    c.check(f"{name} speaker labels", {s["speaker"] for s in ref["segments"]} == {s["speaker"] for s in pxt["segments"]})
    c.check(f"{name} handle time within 1s", abs((ref["handle_time_sec"] or 0) - (pxt["handle_time_sec"] or 0)) <= 1.0,
            f"ref={ref['handle_time_sec']} pxt={pxt['handle_time_sec']}")  # fmt: skip
    c.record(name, {
        "transcript_agreement": round(agreement, 3),
        "segments": {"reference": len(ref["segments"]), "pixeltable": len(pxt["segments"])},
        "sentiment_label": {"reference": (ref["sentiment"] or {}).get("label"), "pixeltable": (pxt["sentiment"] or {}).get("label")},
        "category": {"reference": ref["category"], "pixeltable": pxt["category"]},
    })  # fmt: skip


def main() -> int:
    if not STATE_FILE.is_file():
        print("Missing .compare-state.json. Run: ./scripts/run_compare.sh seed")
        return 1
    state = json.loads(STATE_FILE.read_text())
    manifest = {e["file"]: e for e in load_manifest(fresh_dates=False)}
    ref, pxt = backends()
    c = Checks("parity")

    for api in (ref, pxt):
        health = api.health()
        c.check(f"{api.name} health ok", health["status"] == "ok", json.dumps(health["checks"]))

    for name, ids in state.items():
        ref_call, pxt_call = ref.detail(ids["ref_id"]), pxt.detail(ids["pxt_id"])
        if ref_call is None or pxt_call is None:
            c.check(f"{name} present on both", False, f"ref={ref_call is not None} pxt={pxt_call is not None}")
            continue
        compare_call(c, name, manifest[name], ref_call, pxt_call)
        for api, call_id in ((ref, ids["ref_id"]), (pxt, ids["pxt_id"])):
            c.check(f"{name} {api.name} audio stream", api.media(call_id, "audio") == 200)
            if manifest[name]["media_type"] == "video":
                c.check(f"{name} {api.name} video stream", api.media(call_id, "video") == 200)

    id_key = {"reference": "ref_id", "pixeltable": "pxt_id"}
    seeded = {api.name: {ids[id_key[api.name]] for ids in state.values()} for api in (ref, pxt)}
    for api in (ref, pxt):
        rows = api.list_calls(limit=200)  # newest first
        roster = {row["id"]: row for row in rows}
        c.check(f"{api.name} roster lists every seeded call", seeded[api.name] <= set(roster))
        c.check(f"{api.name} roster statuses completed", all(roster[i]["status"] == "completed" for i in seeded[api.name] if i in roster))
        verticals = {roster[i]["vertical"] for i in seeded[api.name] if i in roster}
        c.check(f"{api.name} roster covers 4 verticals", verticals == {"call_center", "sales", "podcast", "interview"}, str(verticals))
        queue = next(iter(manifest.values()))["queue"]
        c.check(f"{api.name} queue filter", all(r["queue"] == queue for r in api.list_calls(queue=queue)))
        negative = api.list_calls(sentiment_label="negative")
        c.check(f"{api.name} sentiment filter", all(r["sentiment_label"] == "negative" for r in negative))
        # A filter must apply before the limit: at limit=1 each label still returns its newest call.
        for label in sorted({r["sentiment_label"] for r in rows if r["sentiment_label"]}):
            newest = next(r["id"] for r in rows if r["sentiment_label"] == label)
            got = [r["id"] for r in api.list_calls(sentiment_label=label, limit=1)]
            c.check(f"{api.name} sentiment filter before limit ({label})", got == [newest], str(got))
        kpis = api.kpis()
        c.check(f"{api.name} KPIs count the seeded calls", kpis["call_count"] >= len(state), json.dumps(kpis))
        c.record(f"{api.name} kpis", kpis)
        c.record(f"{api.name} flagged", len(api.flagged()))

        for query in ("billing", "cancel"):
            hits = api.search(query, mode="keyword")
            c.check(f"{api.name} keyword {query!r} hits", len(hits) > 0 and all(query in h["text"].lower() for h in hits))
        semantic = api.search("monthly subscription fees", mode="semantic", limit=5)
        c.check(f"{api.name} semantic hits scored", len(semantic) > 0 and all(h["score"] is not None for h in semantic))
        c.check(f"{api.name} hybrid adds semantic hits", any(h["match_type"] == "semantic" for h in api.search("refund", limit=20)))
        c.check(f"{api.name} nonsense query", api.search("zzzznotfound999", mode="keyword") == [])

    write_report("parity", c.report())
    return c.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
