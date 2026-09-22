#!/usr/bin/env python3
"""Data management comparison: schema, counts, storage, reset paths."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import PIXELTABLE, REFERENCE, load_state, print_section, print_table, write_report
from lib.pxt_api import normalize_call_list, unwrap_list


def reference_db_stats() -> dict:
    script = """
import json
import os
from sqlalchemy import text
from app.database import engine
from app.config import settings

stats = {}
with engine.connect() as conn:
    for table in ("calls", "transcript_segments", "coaching_comments"):
        n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        stats[table] = int(n)

upload_dir = settings.upload_dir
size_bytes = 0
file_count = 0
if os.path.isdir(upload_dir):
    for root, _, files in os.walk(upload_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                size_bytes += os.path.getsize(path)
                file_count += 1
            except OSError:
                pass

print(json.dumps({"tables": stats, "upload_dir": upload_dir, "upload_files": file_count, "upload_bytes": size_bytes}))
"""
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=REFERENCE.code_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"error": (result.stderr or result.stdout).strip()}
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {"error": "No JSON output", "raw": result.stdout[-500:]}


def pixeltable_stats() -> dict:
    script = """
import json
import os
import pixeltable as pxt

out = {"tables": {}, "data_dir": os.path.expanduser(os.environ.get("PIXELTABLE_HOME", "~/.pixeltable"))}
try:
    calls = pxt.get_table("call_center.calls")
    out["tables"]["calls"] = int(calls.count())
    out["columns"] = list(calls.columns())
except Exception as exc:
    out["error"] = str(exc)
print(json.dumps(out))
"""
    env = os.environ.copy()
    env.setdefault("PIXELTABLE_HOME", str(ROOT / "data" / "pixeltable"))
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=PIXELTABLE.code_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"error": (result.stderr or result.stdout).strip()}
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    return {"error": "No JSON output from pixeltable stats", "raw": result.stdout[-500:]}


def api_call_counts(client: httpx.Client) -> dict:
    out = {}
    for label, backend in [("reference", REFERENCE), ("pixeltable", PIXELTABLE)]:
        resp = client.get(f"{backend.api}/api/calls")
        if resp.status_code == 200:
            payload = resp.json()
            if label == "pixeltable":
                out[label] = len(normalize_call_list(payload))
            else:
                out[label] = len(payload if isinstance(payload, list) else unwrap_list(payload))
        else:
            out[label] = f"HTTP {resp.status_code}"
    return out


def main() -> int:
    print_section("Data Management")
    state = load_state()
    ref_db = reference_db_stats()
    pxt_db = pixeltable_stats()

    with httpx.Client(timeout=30.0) as client:
        api_counts = api_call_counts(client)

    print("Reference (Postgres + filesystem)")
    if "error" in ref_db:
        print(f"  Error: {ref_db['error']}")
    else:
        print(f"  Tables: {ref_db.get('tables')}")
        print(f"  Upload dir: {ref_db.get('upload_dir')} ({ref_db.get('upload_files')} files, {ref_db.get('upload_bytes')} bytes)")

    print("\nPixeltable (catalog + media store)")
    if "error" in pxt_db:
        print(f"  Error: {pxt_db['error']}")
    else:
        print(f"  Tables: {pxt_db.get('tables')}")
        print(f"  Columns ({len(pxt_db.get('columns', []))}): {', '.join(pxt_db.get('columns', [])[:8])}…")

    print("\nReset mechanisms")
    print("  Reference: TRUNCATE calls/transcript_segments/coaching_comments (seed_compare.py)")
    print("  Pixeltable:  RESET_SCHEMA=true schema.py (seed_compare.py)")

    print_table(
        ["Source", "Call count"],
        [["API reference", api_counts.get("reference")], ["API pixeltable", api_counts.get("pixeltable")]],
    )
    print(f"\nSeeded fixture pairs in .compare-state.json: {len(state)}")

    report = {
        "reference_db": ref_db,
        "pixeltable": pxt_db,
        "api_call_counts": api_counts,
        "seeded_fixtures": len(state),
        "reset": {
            "reference": "scripts/seed_compare.py → TRUNCATE Postgres",
            "pixeltable": "scripts/seed_compare.py → RESET_SCHEMA schema.py",
        },
    }
    path = write_report("data", report)
    print(f"Report: {path}")

    ok = True
    if "error" in ref_db:
        print(f"FAIL: reference DB — {ref_db['error']}")
        ok = False
    if "error" in pxt_db:
        print(f"FAIL: pixeltable — {pxt_db['error']}")
        ok = False

    expected = len(state) if state else 3
    for label, count in api_counts.items():
        if isinstance(count, int) and count < expected:
            print(f"FAIL: {label} API call count {count} < expected {expected} (run seed_compare.py?)")
            ok = False
        elif not isinstance(count, int):
            print(f"FAIL: {label} API — {count}")
            ok = False

    ref_calls = ref_db.get("tables", {}).get("calls") if "error" not in ref_db else None
    pxt_calls = pxt_db.get("tables", {}).get("calls") if "error" not in pxt_db else None
    if isinstance(ref_calls, int) and ref_calls < expected:
        print(f"FAIL: reference DB calls={ref_calls} < expected {expected}")
        ok = False
    if isinstance(pxt_calls, int) and pxt_calls < expected:
        print(f"FAIL: pixeltable calls={pxt_calls} < expected {expected}")
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
