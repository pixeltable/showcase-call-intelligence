#!/usr/bin/env python3
"""Verify setup and health for both backends."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import httpx
from lib.compare_common import PIXELTABLE, REFERENCE, check_health, format_health_checks, print_section, print_table, write_report


def run_verify_setup() -> tuple[int, str]:
    result = subprocess.run(
        ["uv", "run", "python", str(ROOT / "scripts" / "verify_setup.py")],
        cwd=ROOT / "backends" / "pixeltable",
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def reference_db_check() -> dict:
    script = """
import json
from sqlalchemy import text
from app.database import engine
with engine.connect() as conn:
    n = conn.execute(text("SELECT COUNT(*) FROM calls")).scalar()
print(json.dumps({"ok": True, "calls": int(n)}))
"""
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=REFERENCE.code_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or result.stdout).strip()}
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {"ok": False, "error": "No JSON from reference DB check"}


def main() -> int:
    print_section("Setup & Health")
    pxt_code, pxt_out = run_verify_setup()
    print(pxt_out.strip() or "(no output)")

    ref_db = reference_db_check()
    if ref_db.get("ok"):
        print(f"Reference Postgres: OK (calls={ref_db.get('calls')})")
    else:
        print(f"Reference Postgres: FAIL — {ref_db.get('error')}")

    with httpx.Client(timeout=10.0) as client:
        ref_health = check_health(client, REFERENCE)
        pxt_health = check_health(client, PIXELTABLE)

    print_table(
        ["Backend", "API", "Health", "Status", "Latency ms"],
        [
            [
                "Reference",
                REFERENCE.api,
                "OK" if ref_health["ok"] else "FAIL",
                ref_health.get("status", "-"),
                ref_health.get("latency_ms", "-"),
            ],
            [
                "Pixeltable",
                PIXELTABLE.api,
                "OK" if pxt_health["ok"] else "FAIL",
                pxt_health.get("status", "-"),
                pxt_health.get("latency_ms", "-"),
            ],
        ],
    )

    for label, health in [("Reference", ref_health), ("Pixeltable", pxt_health)]:
        if health.get("checks"):
            print(f"\n{label} checks: {format_health_checks(health['checks'])}")
        if health.get("degraded"):
            print(f"  {label} is DEGRADED — failed: {', '.join(health.get('failed_checks') or [])}")

    if ref_health["ok"]:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{REFERENCE.api}/api/calls")
            if resp.status_code == 200:
                queued = sum(1 for c in resp.json() if c.get("status") == "queued")
                if queued:
                    print(
                        f"\nNote: {queued} Reference call(s) still queued — "
                        "ensure Celery worker is running (./scripts/run_compare.sh)"
                    )

    report = {
        "pixeltable_schema_verify": pxt_code == 0,
        "reference_db": ref_db,
        "reference_health": ref_health,
        "pixeltable_health": pxt_health,
    }
    path = write_report("setup", report)
    print(f"\nReport: {path}")

    ok = pxt_code == 0 and ref_health["ok"] and pxt_health["ok"] and ref_db.get("ok")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
