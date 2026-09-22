#!/usr/bin/env python3
"""Production readiness scorecard from compare/reports/*.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "compare" / "reports"


def load(name: str) -> dict:
    path = REPORTS / f"{name}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def ratio(pxt: float | None, ref: float | None) -> str:
    if pxt is None or ref is None or ref == 0:
        return "n/a"
    return f"{round(pxt / ref, 2)}x"


def main() -> int:
    summary = load("summary")
    speed = load("speed")
    observability = load("observability")
    concurrency = load("concurrency")
    mutations = load("mutations")

    print("=" * 60)
    print("Production Readiness Scorecard")
    print("=" * 60)

    exit_codes = summary.get("exit_codes", {})
    gates = summary.get("gates", {})
    gates_passed = summary.get("gates_passed")

    print("\n## Gate results")
    for name, code in exit_codes.items():
        tag = " [gate]" if name in gates else ""
        print(f"  {name}{tag}: {'PASS' if code == 0 else 'FAIL'}")
    print(f"\nOverall gates passed: {'YES' if gates_passed else 'NO' if gates_passed is not None else 'unknown'}")

    print("\n## Correctness & parity")
    parity_ok = exit_codes.get("parity") == 0
    search_ok = exit_codes.get("search") == 0
    print(f"  API parity:        {'PASS' if parity_ok else 'FAIL'}")
    print(f"  Search lineage:    {'PASS' if search_ok else 'FAIL'}")

    print("\n## Reliability")
    obs_ok = exit_codes.get("observability") == 0
    ref_roster = observability.get("roster", {}).get("reference", {})
    pxt_roster = observability.get("roster", {}).get("pixeltable", {})
    print(f"  Observability:     {'PASS' if obs_ok else 'FAIL'}")
    print(f"  Reference statuses: {ref_roster.get('status_counts')}")
    print(f"  Pixeltable statuses: {pxt_roster.get('status_counts')}")

    print("\n## Read performance (p50 ms, Pixeltable / Reference)")
    read = speed.get("read_latency", {})
    for label in (
        "GET /api/calls",
        "GET /api/calls/kpis",
        "GET /api/search?q=billing",
        "GET /api/calls/{id} ref",
        "GET /api/calls/{id} pxt",
    ):
        entry = read.get(label, {})
        ref_p50 = entry.get("reference", {}).get("p50_ms")
        pxt_p50 = entry.get("pixeltable", {}).get("p50_ms")
        if ref_p50 is not None and pxt_p50 is not None:
            print(f"  {label}: ref={ref_p50} pxt={pxt_p50} ratio={ratio(pxt_p50, ref_p50)}")

    print("\n## Upload accept (POST /upload until HTTP response)")
    upload_accept = speed.get("upload_accept", {})
    if upload_accept:
        for key, entry in upload_accept.items():
            if not isinstance(entry, dict):
                continue
            ref = entry.get("reference", {})
            pxt = entry.get("pixeltable", {})
            ref_sec = ref.get("upload_accept_sec")
            pxt_sec = pxt.get("upload_accept_sec")
            if ref_sec is not None and pxt_sec is not None:
                print(f"  {key}: ref={ref_sec}s pxt={pxt_sec}s")
            elif ref.get("note") or pxt.get("note"):
                print(f"  {key}: {ref.get('note') or pxt.get('note')}")

    print("\n## Pipeline complete (upload start → status=completed)")
    pipe = speed.get("pipeline_complete", {})
    legacy = speed.get("pipeline", {})
    sections = pipe or legacy
    if sections:
        if isinstance(sections, dict) and "reference" in sections and "pixeltable" in sections and "call_id" not in sections.get("reference", {}):
            for backend in ("reference", "pixeltable"):
                p = sections.get(backend, {})
                print(f"  {backend}: status={p.get('final_status')} elapsed={p.get('pipeline_complete_sec', p.get('elapsed_sec'))}s")
        else:
            for fixture, entry in sections.items():
                if not isinstance(entry, dict):
                    continue
                ref = entry.get("reference", {})
                pxt = entry.get("pixeltable", {})
                print(
                    f"  {fixture}: ref={ref.get('pipeline_complete_sec')}s "
                    f"pxt={pxt.get('pipeline_complete_sec')}s "
                    f"(accept ref={ref.get('upload_accept_sec')}s pxt={pxt.get('upload_accept_sec')}s)"
                )
    elif concurrency.get("pipeline"):
        for backend in ("reference", "pixeltable"):
            p = concurrency["pipeline"].get(backend, {})
            print(f"  {backend} (concurrency): completed={p.get('completed')} wall={p.get('pipeline_wall_sec')}s")

    print("\n## Mutation lifecycle (comments + delete)")
    mutations_ok = exit_codes.get("mutations") == 0
    print(f"  Comments + delete: {'PASS' if mutations_ok else 'FAIL'}")
    if mutations.get("comments"):
        for backend in ("reference", "pixeltable"):
            count = mutations.get("comments", {}).get(backend, {}).get("comment_count")
            if count is not None:
                print(f"  {backend} comments after POST: {count}")
    if mutations.get("delete", {}).get("after"):
        ref_after = mutations["delete"]["after"].get("reference", {})
        pxt_after = mutations["delete"]["after"].get("pixeltable", {})
        print(
            f"  After delete — ref segments={ref_after.get('segments')} comments={ref_after.get('comments')}; "
            f"pxt call_rows={pxt_after.get('call_rows')} comment_rows={pxt_after.get('comment_rows')}"
        )

    print("\n## Devx & ops burden")
    print("  Reference: Postgres + Celery + Redis + pgvector + manual embed maintenance")
    print("  Pixeltable: unified catalog, auto embedding index, slower read API (.collect())")
    print("  One-command stack: ./scripts/run_compare.sh")
    print("  Clean seed:        ./scripts/run_compare.sh seed")

    print("\n## Script tiers")
    print("  CI gates:     setup, parity, search, speed, data, observability")
    print("  Optional:     concurrency, speed_pipeline, mutations (--full)")
    print("  Informational: patterns, loc")

    assess = {
        "gates_passed": gates_passed,
        "parity_ok": parity_ok,
        "search_ok": search_ok,
        "mutations_ok": mutations_ok,
        "observability_ok": obs_ok,
        "read_latency": read,
        "upload_accept": upload_accept,
        "pipeline_complete": pipe or legacy,
        "pipeline": legacy or pipe,
        "mutations": mutations,
    }
    out = REPORTS / "assess.json"
    out.write_text(json.dumps(assess, indent=2) + "\n")
    print(f"\nReport: {out}")

    ok = gates_passed if gates_passed is not None else all(c == 0 for c in gates.values())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
