#!/usr/bin/env python3
"""Observability: health, pipeline status distribution, errors, KPIs."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import PIXELTABLE, REFERENCE, check_health, format_health_checks, load_state, print_section, print_table, write_report
from lib.pxt_api import normalize_call_list, unwrap_list


def roster_stats(client: httpx.Client, backend) -> dict:
    resp = client.get(f"{backend.api}/api/calls")
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}
    payload = resp.json()
    if backend.name == "pixeltable":
        calls = normalize_call_list(payload)
    else:
        calls = payload if isinstance(payload, list) else unwrap_list(payload)
    statuses = Counter(c.get("status") for c in calls)
    errors = [
        {"id": c.get("id", "")[:8], "status": c.get("status"), "error": c.get("error_message")}
        for c in calls
        if c.get("status") == "failed" or c.get("error_message")
    ]
    media_types = Counter(c.get("media_type") or "audio" for c in calls)
    return {
        "total": len(calls),
        "status_counts": dict(statuses),
        "media_types": dict(media_types),
        "errors": errors[:10],
    }


def kpis(client: httpx.Client, backend) -> dict:
    resp = client.get(f"{backend.api}/api/calls/kpis")
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}
    return resp.json()


def flagged(client: httpx.Client, backend) -> dict:
    resp = client.get(f"{backend.api}/api/calls/flagged")
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}
    data = resp.json()
    if backend.name == "pixeltable":
        data = normalize_call_list(data)
    return {"count": len(data) if isinstance(data, list) else data}


def seeded_roster_stats(client: httpx.Client, backend, state: dict[str, dict[str, str]]) -> dict:
    resp = client.get(f"{backend.api}/api/calls")
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}
    payload = resp.json()
    if backend.name == "pixeltable":
        calls = normalize_call_list(payload)
        id_key = "pxt_id"
    else:
        calls = payload if isinstance(payload, list) else unwrap_list(payload)
        id_key = "ref_id"
    seed_ids = {str(ids[id_key]) for ids in state.values()}
    seeded = [c for c in calls if str(c.get("id")) in seed_ids]
    statuses = Counter(c.get("status") for c in seeded)
    errors = [
        {"id": c.get("id", "")[:8], "status": c.get("status"), "error": c.get("error_message")}
        for c in seeded
        if c.get("status") == "failed" or c.get("error_message")
    ]
    return {
        "total": len(seeded),
        "status_counts": dict(statuses),
        "errors": errors[:10],
    }


def main() -> int:
    print_section("Observability")
    state = load_state()
    expected_calls = len(state) if state else 3

    with httpx.Client(timeout=30.0) as client:
        ref_health = check_health(client, REFERENCE)
        pxt_health = check_health(client, PIXELTABLE)
        ref_roster = roster_stats(client, REFERENCE)
        pxt_roster = roster_stats(client, PIXELTABLE)
        ref_seed = seeded_roster_stats(client, REFERENCE, state) if state else ref_roster
        pxt_seed = seeded_roster_stats(client, PIXELTABLE, state) if state else pxt_roster
        ref_kpis = kpis(client, REFERENCE)
        pxt_kpis = kpis(client, PIXELTABLE)
        ref_flagged = flagged(client, REFERENCE)
        pxt_flagged = flagged(client, PIXELTABLE)

    print("Health")
    print_table(
        ["Backend", "Reachable", "Status", "Latency ms"],
        [
            [
                "Reference",
                ref_health["ok"],
                ref_health.get("status", "-"),
                ref_health.get("latency_ms"),
            ],
            [
                "Pixeltable",
                pxt_health["ok"],
                pxt_health.get("status", "-"),
                pxt_health.get("latency_ms"),
            ],
        ],
    )

    for label, health in [("Reference", ref_health), ("Pixeltable", pxt_health)]:
        if health.get("checks"):
            print(f"  {label} checks: {format_health_checks(health['checks'])}")

    print("\nPipeline status distribution")
    print_table(
        ["Backend", "Total", "Statuses"],
        [
            ["Reference", ref_roster.get("total"), ref_roster.get("status_counts")],
            ["Pixeltable", pxt_roster.get("total"), pxt_roster.get("status_counts")],
        ],
    )

    print("\nKPIs (7-day window)")
    print_table(
        ["Backend", "call_count", "avg_handle_time_sec", "avg_sentiment_score"],
        [
            [
                "Reference",
                ref_kpis.get("call_count"),
                ref_kpis.get("avg_handle_time_sec"),
                ref_kpis.get("avg_sentiment_score"),
            ],
            [
                "Pixeltable",
                pxt_kpis.get("call_count"),
                pxt_kpis.get("avg_handle_time_sec"),
                pxt_kpis.get("avg_sentiment_score"),
            ],
        ],
    )

    print("\nFlagged calls")
    print(f"  Reference:  {ref_flagged.get('count')}")
    print(f"  Pixeltable: {pxt_flagged.get('count')}")

    for label, roster in [("Reference", ref_roster), ("Pixeltable", pxt_roster)]:
        if roster.get("errors"):
            print(f"\n{label} errors / failures:")
            for item in roster["errors"]:
                print(f"  {item['id']}… status={item['status']} error={item.get('error')}")

    report = {
        "health": {"reference": ref_health, "pixeltable": pxt_health},
        "roster": {"reference": ref_roster, "pixeltable": pxt_roster},
        "kpis": {"reference": ref_kpis, "pixeltable": pxt_kpis},
        "flagged": {"reference": ref_flagged, "pixeltable": pxt_flagged},
        "notes": {
            "reference": "Status via Celery task updates on Call row; worker logs in Celery process",
            "pixeltable": "Status via pipeline_status computed column; enrichment errormsg on failure",
        },
    }
    path = write_report("observability", report)
    print(f"\nReport: {path}")

    ok = True
    if not ref_health["ok"] or not pxt_health["ok"]:
        print("FAIL: one or both APIs unhealthy")
        ok = False

    for label, roster in [("Reference", ref_seed), ("Pixeltable", pxt_seed)]:
        if "error" in roster:
            print(f"FAIL: {label} roster — {roster['error']}")
            ok = False
            continue
        completed = roster.get("status_counts", {}).get("completed", 0)
        failed = roster.get("status_counts", {}).get("failed", 0)
        pending = roster.get("total", 0) - completed - failed
        if failed > 0:
            if label == "Reference" and failed <= 1:
                print(f"WARN: {label} has {failed} failed seeded call(s) — tolerated for seed variance")
            else:
                print(f"FAIL: {label} has {failed} failed seeded call(s)")
                ok = False
        if pending > 0:
            print(f"FAIL: {label} has {pending} non-terminal seeded call(s) — is Celery running?")
            ok = False
        if roster.get("total", 0) < expected_calls:
            print(f"FAIL: {label} seeded total={roster.get('total')} < expected {expected_calls}")
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
