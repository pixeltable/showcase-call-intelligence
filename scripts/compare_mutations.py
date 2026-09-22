#!/usr/bin/env python3
"""Comment and delete lifecycle parity between Reference and Pixeltable."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import (
    FIXTURES,
    PIXELTABLE,
    REFERENCE,
    delete_call,
    pixeltable_call_stats,
    post_comment,
    print_section,
    print_table,
    reference_call_stats,
    upload_and_wait,
    write_report,
)
from lib.pxt_api import normalize_call_list, normalize_search_list, unwrap_list

MUTATION_FIXTURE = "billing-inquiry-speech.wav"
AGENT_SUFFIX = "mutation-test"


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


def load_fixture_meta() -> dict:
    manifest_path = FIXTURES / "manifest.json"
    for entry in json.loads(manifest_path.read_text()):
        if entry["file"] == MUTATION_FIXTURE:
            return entry
    raise FileNotFoundError(f"Fixture {MUTATION_FIXTURE} not in manifest")


def search_hits_for_call(client: httpx.Client, backend, call_id: str, query: str = "billing") -> list[dict]:
    resp = client.get(f"{backend.api}/api/search", params={"q": query, "mode": "hybrid"})
    if resp.status_code != 200:
        return []
    payload = resp.json()
    if backend.name == "pixeltable":
        hits = normalize_search_list(payload)
    else:
        hits = payload if isinstance(payload, list) else []
    return [h for h in hits if str(h.get("call_id")) == call_id]


def roster_contains(client: httpx.Client, backend, call_id: str) -> bool:
    resp = client.get(f"{backend.api}/api/calls")
    if resp.status_code != 200:
        return False
    payload = resp.json()
    if backend.name == "pixeltable":
        rows = normalize_call_list(payload)
    else:
        rows = payload if isinstance(payload, list) else unwrap_list(payload)
    return any(str(c.get("id")) == call_id for c in rows)


def verify_comments(ref_call: dict, pxt_call: dict) -> tuple[bool, dict]:
    results: list[bool] = []
    report: dict = {"reference": {}, "pixeltable": {}}

    for label, backend_name, call in [("reference", "reference", ref_call), ("pixeltable", "pixeltable", pxt_call)]:
        comments = call.get("comments") or []
        report[backend_name]["comment_count"] = len(comments)
        results.append(check(f"{label} comment count", len(comments) == 2, f"got {len(comments)}"))
        anchored = [c for c in comments if c.get("segment_id")]
        call_level = [c for c in comments if not c.get("segment_id")]
        results.append(check(f"{label} anchored comment", len(anchored) == 1))
        results.append(check(f"{label} call-level comment", len(call_level) == 1))
        if anchored:
            results.append(check(
                f"{label} anchored author",
                anchored[0].get("author") == "qa-reviewer",
            ))
            results.append(check(
                f"{label} anchored segment_id present",
                bool(anchored[0].get("segment_id")),
            ))

    return all(results), report


def run_comment_phase(client: httpx.Client, ref_call: dict, pxt_call: dict) -> tuple[bool, dict]:
    results: list[bool] = []
    phase: dict = {"reference": {}, "pixeltable": {}}

    for label, backend, call in [("reference", REFERENCE, ref_call), ("pixeltable", PIXELTABLE, pxt_call)]:
        segments = call.get("segments") or []
        if not segments:
            results.append(check(f"{label} has segments", False))
            continue
        seg = segments[0]
        anchored = post_comment(client, backend, {
            "call_id": call["id"],
            "segment_id": seg["id"],
            "start_sec": seg["start_sec"],
            "author": "qa-reviewer",
            "comment": "Segment coaching note from compare_mutations",
        })
        call_level = post_comment(client, backend, {
            "call_id": call["id"],
            "start_sec": 0.0,
            "author": "qa-reviewer",
            "comment": "Call-level coaching note from compare_mutations",
        })
        phase[label]["anchored_comment_id"] = str(anchored.get("id"))
        phase[label]["call_level_comment_id"] = str(call_level.get("id"))
        results.append(check(f"{label} POST comments", True))

    ref_detail = client.get(f"{REFERENCE.api}/api/calls/{ref_call['id']}")
    from lib.pxt_api import fetch_call_detail

    pxt_detail_json = fetch_call_detail(client, PIXELTABLE.api, pxt_call["id"])
    results.append(check("reference GET detail", ref_detail.status_code == 200))
    results.append(check("pixeltable GET detail", bool(pxt_detail_json)))
    if ref_detail.status_code == 200 and pxt_detail_json:
        ok, comment_report = verify_comments(ref_detail.json(), pxt_detail_json)
        phase.update(comment_report)
        results.append(ok)

    ref_hits = search_hits_for_call(client, REFERENCE, ref_call["id"])
    pxt_hits = search_hits_for_call(client, PIXELTABLE, pxt_call["id"])
    results.append(check("reference search still returns hits", len(ref_hits) > 0, f"hits={len(ref_hits)}"))
    results.append(check("pixeltable search still returns hits", len(pxt_hits) > 0, f"hits={len(pxt_hits)}"))
    phase["search_hits_before_delete"] = {"reference": len(ref_hits), "pixeltable": len(pxt_hits)}

    return all(results), phase


def run_delete_phase(
    client: httpx.Client,
    ref_call: dict,
    pxt_call: dict,
) -> tuple[bool, dict]:
    results: list[bool] = []
    phase: dict = {"reference": {}, "pixeltable": {}}

    ref_id = str(ref_call["id"])
    pxt_id = str(pxt_call["id"])

    ref_stats_before = reference_call_stats(ref_id)
    pxt_stats_before = pixeltable_call_stats(pxt_id)
    phase["before"] = {"reference": ref_stats_before, "pixeltable": pxt_stats_before}

    ref_status = delete_call(client, REFERENCE, ref_id)
    pxt_status = delete_call(client, PIXELTABLE, pxt_id)
    results.append(check("reference DELETE status", ref_status == 204, f"got {ref_status}"))
    results.append(check("pixeltable DELETE status", pxt_status == 204, f"got {pxt_status}"))

    ref_get = client.get(f"{REFERENCE.api}/api/calls/{ref_id}")
    pxt_get = client.get(f"{PIXELTABLE.api}/api/calls/{pxt_id}")
    results.append(check("reference GET after delete", ref_get.status_code == 404))
    results.append(check("pixeltable GET after delete", pxt_get.status_code == 404))
    results.append(check("reference absent from roster", not roster_contains(client, REFERENCE, ref_id)))
    results.append(check("pixeltable absent from roster", not roster_contains(client, PIXELTABLE, pxt_id)))

    ref_search = search_hits_for_call(client, REFERENCE, ref_id)
    pxt_search = search_hits_for_call(client, PIXELTABLE, pxt_id)
    results.append(check("reference search no deleted hits", len(ref_search) == 0))
    results.append(check("pixeltable search no deleted hits", len(pxt_search) == 0))

    ref_stats = reference_call_stats(ref_id)
    pxt_stats = pixeltable_call_stats(pxt_id)
    phase["after"] = {"reference": ref_stats, "pixeltable": pxt_stats}

    results.append(check(
        "reference segments cleaned",
        ref_stats.get("segments") == 0 and not ref_stats.get("call_exists"),
        f"segments={ref_stats.get('segments')} exists={ref_stats.get('call_exists')}",
    ))
    results.append(check(
        "reference comments cleaned",
        ref_stats.get("comments") == 0,
        f"comments={ref_stats.get('comments')}",
    ))
    results.append(check(
        "reference upload files removed",
        not ref_stats.get("audio_exists") and not ref_stats.get("video_exists"),
        f"audio={ref_stats.get('audio_exists')} video={ref_stats.get('video_exists')}",
    ))
    results.append(check(
        "pixeltable call row removed",
        pxt_stats.get("call_rows") == 0,
        f"call_rows={pxt_stats.get('call_rows')}",
    ))
    results.append(check(
        "pixeltable comments removed",
        pxt_stats.get("comment_rows") == 0,
        f"comment_rows={pxt_stats.get('comment_rows')}",
    ))
    view_rows = pxt_stats.get("view_segment_rows")
    if view_rows is not None:
        results.append(check(
            "pixeltable view segments removed",
            view_rows == 0,
            f"view_segment_rows={view_rows}",
        ))

    return all(results), phase


def main() -> int:
    meta = load_fixture_meta()
    fixture_path = FIXTURES / MUTATION_FIXTURE
    if not fixture_path.is_file():
        print(f"Missing fixture: {fixture_path}")
        return 1

    all_ok = True
    report: dict = {"fixture": MUTATION_FIXTURE, "agent_suffix": AGENT_SUFFIX}

    print_section("Upload ephemeral calls (mutation-test)")
    with httpx.Client(timeout=60.0) as client:
        try:
            ref_call = upload_and_wait(client, REFERENCE, fixture_path, meta, agent_suffix=AGENT_SUFFIX)
            pxt_call = upload_and_wait(client, PIXELTABLE, fixture_path, meta, agent_suffix=AGENT_SUFFIX)
        except (RuntimeError, TimeoutError) as exc:
            print(f"  [FAIL] upload/wait — {exc}")
            return 1

        print_table(
            ["Backend", "Call ID", "Status", "Segments"],
            [
                ["Reference", str(ref_call["id"])[:8], ref_call.get("status"), len(ref_call.get("segments") or [])],
                ["Pixeltable", str(pxt_call["id"])[:8], pxt_call.get("status"), len(pxt_call.get("segments") or [])],
            ],
        )
        report["upload"] = {
            "reference": {"call_id": ref_call["id"], "segments": len(ref_call.get("segments") or [])},
            "pixeltable": {"call_id": pxt_call["id"], "segments": len(pxt_call.get("segments") or [])},
        }

        print_section("Phase A — Coaching comments")
        comment_ok, comment_phase = run_comment_phase(client, ref_call, pxt_call)
        report["comments"] = comment_phase
        all_ok = all_ok and comment_ok

        print_section("Phase B — Delete + cleanup")
        delete_ok, delete_phase = run_delete_phase(client, ref_call, pxt_call)
        report["delete"] = delete_phase
        all_ok = all_ok and delete_ok

    path = write_report("mutations", report)
    print(f"\nReport: {path}")
    print(f"\nMutations gate: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
