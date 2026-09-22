#!/usr/bin/env python3
"""End-to-end smoke test: upload sample, poll pipeline, assert intelligence fields."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DEFAULT_SAMPLE = ROOT / "compare" / "fixtures" / "billing-inquiry-speech.wav"
POLL_SEC = 5
TIMEOUT_SEC = 600

BACKENDS = {
    "ref": os.getenv("REF_API", "http://127.0.0.1:8001"),
    "pxt": os.getenv("PXT_API", "http://127.0.0.1:8000"),
}


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def run_smoke(api_base: str, label: str, sample: Path) -> int:
    print(f"\n=== Smoke test: {label} ({api_base}) ===")
    is_pixeltable = api_base.rstrip("/") == BACKENDS["pxt"].rstrip("/")
    with httpx.Client(base_url=api_base, timeout=120.0) as client:
        health = client.get("/api/health")
        if health.status_code != 200:
            return fail(f"{label} API health check failed: {health.status_code}")

        if is_pixeltable:
            from lib.pxt_api import fetch_call_detail, upload_pixeltable_fixture, wait_for_pixeltable_call

            entry = {
                "call_date": datetime.now(timezone.utc).isoformat(),
                "agent_id": "agent-smoke",
                "customer_id": "cust-smoke",
                "queue": "billing",
                "vertical": "call_center",
            }
            call_uuid = upload_pixeltable_fixture(
                client,
                api_base,
                path=sample,
                entry=entry,
                mime="audio/wav",
                timeout=120.0,
            )
            print(f"Uploaded call {call_uuid} (native insert job)")
            call = wait_for_pixeltable_call(
                client,
                api_base,
                call_uuid,
                poll_sec=POLL_SEC,
                timeout_sec=TIMEOUT_SEC,
            )
        else:
            with sample.open("rb") as handle:
                upload = client.post(
                    "/api/calls/upload",
                    data={
                        "call_date": datetime.now(timezone.utc).isoformat(),
                        "agent_id": "agent-smoke",
                        "customer_id": "cust-smoke",
                        "queue": "billing",
                    },
                    files={"audio": (sample.name, handle, "audio/wav")},
                )
            if upload.status_code not in (200, 202):
                return fail(f"{label} upload failed: {upload.status_code} {upload.text}")

            payload = upload.json()
            call_uuid = str(payload.get("id"))
            if not call_uuid:
                return fail(f"{label} upload response missing call id")

            print(f"Uploaded call {call_uuid} (status={payload.get('status')})")

            deadline = time.time() + TIMEOUT_SEC
            call = None
            while time.time() < deadline:
                detail = client.get(f"/api/calls/{call_uuid}")
                if detail.status_code != 200:
                    time.sleep(POLL_SEC)
                    continue
                call = detail.json()
                status = call.get("status")
                print(f"  status={status}")
                if status == "failed":
                    return fail(f"{label}: {call.get('error_message') or 'Pipeline failed'}")
                if status == "completed":
                    break
                time.sleep(POLL_SEC)
            if call is None or call.get("status") != "completed":
                return fail(f"{label}: timed out after {TIMEOUT_SEC}s")

        sentiment = call.get("sentiment") or {}
        if not call.get("summary"):
            return fail(f"{label}: missing summary")
        if not call.get("category"):
            return fail(f"{label}: missing category")
        if sentiment.get("label") not in {"positive", "neutral", "negative", "unknown"}:
            return fail(f"{label}: unexpected sentiment label: {sentiment.get('label')}")
        flags = sentiment.get("flags") or sentiment.get("moments") or []
        print(
            f"  PASS sentiment={sentiment.get('label')} flags={len(flags)} "
            f"category={call.get('category')} segments={len(call.get('segments') or [])}"
        )
        return 0

    return fail(f"{label}: timed out after {TIMEOUT_SEC}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E smoke test for call center backends")
    parser.add_argument("sample", nargs="?", type=Path, default=DEFAULT_SAMPLE, help="Audio sample path")
    parser.add_argument(
        "--backend",
        choices=["ref", "pxt", "both"],
        default="both",
        help="Which backend to test (default: both)",
    )
    parser.add_argument("--api-url", help="Override API base URL (single-backend only)")
    args = parser.parse_args()

    if not args.sample.is_file():
        return fail(f"Sample not found: {args.sample}")

    if args.api_url:
        return run_smoke(args.api_url.rstrip("/"), "custom", args.sample)

    codes = []
    if args.backend in ("ref", "both"):
        codes.append(run_smoke(BACKENDS["ref"], "Reference", args.sample))
    if args.backend in ("pxt", "both"):
        codes.append(run_smoke(BACKENDS["pxt"], "Pixeltable", args.sample))

    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
