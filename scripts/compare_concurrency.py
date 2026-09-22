#!/usr/bin/env python3
"""Concurrency comparison: parallel uploads to both backends."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import FIXTURES, PIXELTABLE, REFERENCE, UPLOAD_TIMEOUT_SEC, print_section, print_table, upload_fixture, write_report

MIME = {".wav": "audio/wav", ".mp4": "video/mp4"}


def upload_one(base_url: str, entry: dict, suffix: str) -> dict:
    path = FIXTURES / entry["file"]
    backend = PIXELTABLE if base_url.rstrip("/") == PIXELTABLE.api.rstrip("/") else REFERENCE
    meta = {**entry, "agent_id": f"{entry['agent_id']}-conc-{suffix}"}
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=UPLOAD_TIMEOUT_SEC) as client:
            call_id = upload_fixture(client, backend, path, meta)
        elapsed = time.perf_counter() - started
        return {
            "ok": True,
            "status_code": 202,
            "call_id": call_id,
            "upload_sec": round(elapsed, 2),
            "file": entry["file"],
        }
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return {
            "ok": False,
            "status_code": 0,
            "call_id": None,
            "upload_sec": round(elapsed, 2),
            "file": entry["file"],
            "error": str(exc),
        }


def parallel_uploads(base_url: str, entries: list[dict], workers: int) -> dict:
    started = time.perf_counter()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(upload_one, base_url, entry, str(i))
            for i, entry in enumerate(entries)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    wall_sec = round(time.perf_counter() - started, 2)
    ok = sum(1 for r in results if r["ok"])
    return {
        "workers": workers,
        "uploads": len(results),
        "ok": ok,
        "failed": len(results) - ok,
        "wall_sec": wall_sec,
        "avg_upload_sec": round(sum(r["upload_sec"] for r in results) / len(results), 2) if results else 0,
        "results": results,
    }


def wait_all_complete(base_url: str, call_ids: list[str], timeout_sec: int = 600) -> dict:
    deadline = time.time() + timeout_sec
    statuses: dict[str, str] = {}
    started = time.perf_counter()
    with httpx.Client(timeout=30.0) as client:
        while time.time() < deadline:
            pending = [cid for cid in call_ids if cid and statuses.get(cid) not in {"completed", "failed"}]
            if not pending:
                break
            for cid in pending:
                resp = client.get(f"{base_url}/api/calls/{cid}")
                if resp.status_code == 200:
                    body = resp.json()
                    status = body.get("status") or body.get("pipeline_status") or "unknown"
                    if base_url.rstrip("/") == PIXELTABLE.api.rstrip("/") and status == "completed":
                        embed = client.get(f"{base_url}/api/calls/{cid}/embed-ready", timeout=10.0)
                        if embed.status_code == 200 and not embed.json().get("embed_ready"):
                            continue
                    statuses[cid] = status
            time.sleep(3)
    elapsed = round(time.perf_counter() - started, 2)
    completed = sum(1 for s in statuses.values() if s == "completed")
    failed = sum(1 for s in statuses.values() if s == "failed")
    return {
        "tracked": len(call_ids),
        "completed": completed,
        "failed": failed,
        "pending": len(call_ids) - completed - failed,
        "pipeline_wall_sec": elapsed,
        "statuses": statuses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Parallel upload concurrency test")
    parser.add_argument("--workers", type=int, default=3, help="Parallel upload threads per backend")
    parser.add_argument("--wait", action="store_true", help="Wait for all pipelines to finish")
    args = parser.parse_args()

    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    print_section(f"Parallel uploads ({args.workers} workers × {len(manifest)} fixtures)")

    ref = parallel_uploads(REFERENCE.api, manifest, args.workers)
    pxt = parallel_uploads(PIXELTABLE.api, manifest, args.workers)

    print_table(
        ["Backend", "OK", "Failed", "Wall sec", "Avg upload sec"],
        [
            ["Reference", ref["ok"], ref["failed"], ref["wall_sec"], ref["avg_upload_sec"]],
            ["Pixeltable", pxt["ok"], pxt["failed"], pxt["wall_sec"], pxt["avg_upload_sec"]],
        ],
    )

    report: dict = {"upload": {"reference": ref, "pixeltable": pxt}}
    if args.wait:
        print_section("Pipeline completion after parallel uploads")
        ref_ids = [r["call_id"] for r in ref["results"] if r.get("call_id")]
        pxt_ids = [r["call_id"] for r in pxt["results"] if r.get("call_id")]
        ref_done = wait_all_complete(REFERENCE.api, ref_ids)
        pxt_done = wait_all_complete(PIXELTABLE.api, pxt_ids)
        report["pipeline"] = {"reference": ref_done, "pixeltable": pxt_done}
        print_table(
            ["Backend", "Completed", "Failed", "Pending", "Pipeline wall sec"],
            [
                [
                    "Reference",
                    ref_done["completed"],
                    ref_done["failed"],
                    ref_done["pending"],
                    ref_done["pipeline_wall_sec"],
                ],
                [
                    "Pixeltable",
                    pxt_done["completed"],
                    pxt_done["failed"],
                    pxt_done["pending"],
                    pxt_done["pipeline_wall_sec"],
                ],
            ],
        )

    path = write_report("concurrency", report)
    print(f"\nReport: {path}")
    print("Note: both backends return 202 quickly; pipeline completion is measured separately with --wait.")
    return 0 if ref["failed"] == 0 and pxt["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
