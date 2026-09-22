#!/usr/bin/env python3
"""API latency and pipeline timing benchmarks."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import (
    FIXTURES,
    PIXELTABLE,
    REFERENCE,
    UPLOAD_TIMEOUT_SEC,
    load_state,
    print_section,
    print_table,
    timed_request,
    upload_fixture as common_upload_fixture,
    write_report,
)

PIPELINE_RATIO_MAX = 3.0


def upload_fixture(client: httpx.Client, backend, fixture_path: Path, meta: dict) -> str:
    return common_upload_fixture(client, backend, fixture_path, meta)


def bench_endpoint(client: httpx.Client, base: str, method: str, path: str, *, rounds: int = 10) -> dict:
    latencies: list[float] = []
    ok = True
    for _ in range(rounds):
        result = timed_request(client, method, f"{base}{path}")
        latencies.append(result["latency_ms"])
        ok = ok and result["ok"]
    return {
        "ok": ok,
        "rounds": rounds,
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2),
        "min_ms": round(min(latencies), 2),
        "max_ms": round(max(latencies), 2),
    }


def bench_pipeline(client: httpx.Client, backend, call_id: str, *, started: float | None = None) -> dict:
    poll_started = time.perf_counter()
    deadline = poll_started + 600
    last_status = None
    last_code = None
    while time.perf_counter() < deadline:
        resp = client.get(f"{backend.api}/api/calls/{call_id}")
        last_code = resp.status_code
        if resp.status_code == 200:
            body = resp.json()
            last_status = body.get("status") or body.get("pipeline_status")
            if last_status in {"completed", "failed"}:
                if backend.name == "pixeltable" and last_status == "completed":
                    embed = client.get(f"{backend.api}/api/calls/{call_id}/embed-ready", timeout=10.0)
                    if embed.status_code == 200 and not embed.json().get("embed_ready"):
                        time.sleep(3)
                        continue
                poll_elapsed = time.perf_counter() - poll_started
                total_elapsed = time.perf_counter() - started if started is not None else poll_elapsed
                return {
                    "call_id": call_id,
                    "final_status": last_status,
                    "elapsed_sec": round(poll_elapsed, 2),
                    "pipeline_complete_sec": round(total_elapsed, 2),
                }
        time.sleep(3)
    poll_elapsed = time.perf_counter() - poll_started
    total_elapsed = time.perf_counter() - started if started is not None else poll_elapsed
    return {
        "call_id": call_id,
        "final_status": last_status,
        "elapsed_sec": None,
        "pipeline_complete_sec": None,
        "timeout": True,
        "last_http_status": last_code,
    }


def bench_upload_and_pipeline(
    client: httpx.Client,
    backend,
    fixture_path: Path,
    meta: dict,
) -> dict:
    t0 = time.perf_counter()
    call_id = upload_fixture(client, backend, fixture_path, meta)
    accept_sec = time.perf_counter() - t0
    pipe = bench_pipeline(client, backend, call_id, started=t0)
    return {
        "fixture": fixture_path.name,
        "call_id": call_id,
        "upload_accept_sec": round(accept_sec, 3),
        "pipeline_complete_sec": pipe.get("pipeline_complete_sec"),
        "poll_elapsed_sec": pipe.get("elapsed_sec"),
        "final_status": pipe.get("final_status"),
        "timeout": pipe.get("timeout", False),
    }


def load_manifest() -> list[dict]:
    manifest_path = FIXTURES / "manifest.json"
    if not manifest_path.is_file():
        return []
    return json.loads(manifest_path.read_text())


def pipeline_gate_ok(ref: dict, pxt: dict) -> tuple[bool, str]:
    for label, result in [("Reference", ref), ("Pixeltable", pxt)]:
        if result.get("final_status") != "completed":
            return False, f"{label} pipeline status={result.get('final_status')}"
        if result.get("pipeline_complete_sec") is None:
            return False, f"{label} pipeline timed out"
        accept = result.get("upload_accept_sec")
        if accept is not None and accept > UPLOAD_TIMEOUT_SEC:
            return False, f"{label} upload accept took {accept}s (max {UPLOAD_TIMEOUT_SEC}s)"

    ref_sec = float(ref["pipeline_complete_sec"])
    pxt_sec = float(pxt["pipeline_complete_sec"])
    if ref_sec <= 0:
        return True, ""
    ratio = pxt_sec / ref_sec
    if ratio > PIPELINE_RATIO_MAX:
        return False, f"pipeline ratio {ratio:.1f}x exceeds {PIPELINE_RATIO_MAX}x cap"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark API speed for both backends")
    parser.add_argument("--rounds", type=int, default=10, help="Iterations per read endpoint")
    parser.add_argument("--pipeline", action="store_true", help="Measure upload accept + pipeline completion timing")
    parser.add_argument(
        "--fresh-pipeline",
        action="store_true",
        help="Upload fixture(s) to both backends before pipeline timing",
    )
    parser.add_argument(
        "--pipeline-all",
        action="store_true",
        help="With --fresh-pipeline, run on all manifest fixtures (slow)",
    )
    args = parser.parse_args()

    state = load_state()
    first_ref = next(iter(state.values()), {}).get("ref_id") if state else None
    first_pxt = next(iter(state.values()), {}).get("pxt_id") if state else None

    ok = True
    print_section(f"Read API latency ({args.rounds} rounds)")
    with httpx.Client(timeout=60.0) as client:
        endpoints: list[tuple[str, str, str, bool, bool]] = [
            ("GET /api/calls", "GET", "/api/calls", True, True),
            ("GET /api/calls/kpis", "GET", "/api/calls/kpis", True, True),
            ("GET /api/calls/flagged", "GET", "/api/calls/flagged", True, True),
            ("GET /api/search?q=billing", "GET", "/api/search?q=billing", True, True),
        ]
        if first_ref:
            endpoints.append(("GET /api/calls/{id} ref", "GET", f"/api/calls/{first_ref}", True, False))
        if first_pxt:
            endpoints.append(("GET /api/calls/{id} pxt", "GET", f"/api/calls/{first_pxt}", False, True))

        rows = []
        report: dict = {"read_latency": {}, "upload_accept": {}, "pipeline_complete": {}}
        for label, method, path, bench_ref, bench_pxt in endpoints:
            ref = (
                bench_endpoint(client, REFERENCE.api, method, path, rounds=args.rounds)
                if bench_ref
                else {"ok": True, "p50_ms": None, "p95_ms": None}
            )
            pxt = (
                bench_endpoint(client, PIXELTABLE.api, method, path, rounds=args.rounds)
                if bench_pxt
                else {"ok": True, "p50_ms": None, "p95_ms": None}
            )
            rows.append([
                label,
                ref["p50_ms"] if ref["p50_ms"] is not None else "-",
                ref["p95_ms"] if ref["p95_ms"] is not None else "-",
                pxt["p50_ms"] if pxt["p50_ms"] is not None else "-",
                pxt["p95_ms"] if pxt["p95_ms"] is not None else "-",
            ])
            report["read_latency"][label] = {"reference": ref, "pixeltable": pxt}
            if bench_ref and not ref["ok"]:
                ok = False
                print(f"  FAIL: {label} — reference HTTP errors")
            if bench_pxt and not pxt["ok"]:
                ok = False
                print(f"  FAIL: {label} — pixeltable HTTP errors")

        print_table(["Endpoint", "Ref p50", "Ref p95", "Pxt p50", "Pxt p95"], rows)

        if args.pipeline:
            manifest = load_manifest()
            fixtures: list[tuple[Path, dict]] = []
            if args.fresh_pipeline:
                if args.pipeline_all:
                    for entry in manifest:
                        path = FIXTURES / entry["file"]
                        if path.is_file():
                            fixtures.append((path, entry))
                else:
                    entry = next((e for e in manifest if e["file"] == "billing-inquiry-speech.wav"), None)
                    path = FIXTURES / "billing-inquiry-speech.wav"
                    if entry and path.is_file():
                        fixtures = [(path, entry)]
                    else:
                        print("Warning: fresh-pipeline skipped — billing-inquiry-speech.wav not found")
                        ok = False
            elif first_ref and first_pxt:
                ref_pipe = bench_pipeline(client, REFERENCE, first_ref)
                pxt_pipe = bench_pipeline(client, PIXELTABLE, first_pxt)
                report["upload_accept"] = {
                    "reference": {"note": "seeded call; upload accept not measured"},
                    "pixeltable": {"note": "seeded call; upload accept not measured"},
                }
                report["pipeline_complete"] = {
                    "reference": ref_pipe,
                    "pixeltable": pxt_pipe,
                }
                print_section("Pipeline poll (seeded calls — upload accept not measured)")
                print_table(
                    ["Backend", "Call", "Status", "Poll sec"],
                    [
                        ["Reference", (first_ref or "")[:8], ref_pipe.get("final_status"), ref_pipe.get("elapsed_sec")],
                        ["Pixeltable", (first_pxt or "")[:8], pxt_pipe.get("final_status"), pxt_pipe.get("elapsed_sec")],
                    ],
                )
                gate_ok, detail = pipeline_gate_ok(
                    {"final_status": ref_pipe.get("final_status"), "pipeline_complete_sec": ref_pipe.get("elapsed_sec")},
                    {"final_status": pxt_pipe.get("final_status"), "pipeline_complete_sec": pxt_pipe.get("elapsed_sec")},
                )
                if not gate_ok:
                    ok = False
                    print(f"  FAIL: {detail}")
            else:
                print("Warning: no seeded state; use --fresh-pipeline or run seed_compare.py")
                ok = False

            for fixture_path, meta in fixtures:
                print_section(f"Upload + pipeline ({fixture_path.name})")
                ref_result = bench_upload_and_pipeline(client, REFERENCE, fixture_path, meta)
                pxt_result = bench_upload_and_pipeline(client, PIXELTABLE, fixture_path, meta)
                key = fixture_path.name
                report["upload_accept"][key] = {
                    "reference": {
                        "upload_accept_sec": ref_result["upload_accept_sec"],
                        "call_id": ref_result["call_id"],
                    },
                    "pixeltable": {
                        "upload_accept_sec": pxt_result["upload_accept_sec"],
                        "call_id": pxt_result["call_id"],
                    },
                }
                report["pipeline_complete"][key] = {
                    "reference": ref_result,
                    "pixeltable": pxt_result,
                }
                print_table(
                    ["Backend", "Accept sec", "Pipeline sec", "Status"],
                    [
                        [
                            "Reference",
                            ref_result["upload_accept_sec"],
                            ref_result["pipeline_complete_sec"],
                            ref_result["final_status"],
                        ],
                        [
                            "Pixeltable",
                            pxt_result["upload_accept_sec"],
                            pxt_result["pipeline_complete_sec"],
                            pxt_result["final_status"],
                        ],
                    ],
                )
                gate_ok, detail = pipeline_gate_ok(ref_result, pxt_result)
                if not gate_ok:
                    ok = False
                    print(f"  FAIL: {detail}")

    path = write_report("speed", report)
    print(f"\nReport: {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
