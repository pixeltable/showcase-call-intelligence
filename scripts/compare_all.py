#!/usr/bin/env python3
"""Run all comparison reports (setup, patterns, loc, speed, data, concurrency, observability)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import ensure_reports_dir, write_report

GATE_SCRIPTS = [
    ("setup", ["compare_setup.py"]),
    ("parity", ["compare_parity.py"]),
    ("search", ["compare_search.py"]),
]

INFO_SCRIPTS = [
    ("patterns", ["compare_patterns.py"]),
    ("loc", ["compare_loc.py"]),
]

PERF_SCRIPTS = [
    ("speed", ["compare_speed.py", "--rounds", "5"]),
    ("data", ["compare_data.py"]),
    ("observability", ["compare_observability.py"]),
]


def run_script(name: str, args: list[str]) -> int:
    cmd = ["uv", "run", "python", str(ROOT / "scripts" / args[0]), *args[1:]]
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full backend comparison suite")
    parser.add_argument("--with-concurrency", action="store_true", help="Include parallel upload test (creates extra calls)")
    parser.add_argument(
        "--with-pipeline-speed",
        action="store_true",
        help="Include pipeline timing in speed report (uses --fresh-pipeline)",
    )
    parser.add_argument(
        "--with-mutations",
        action="store_true",
        help="Include comment + delete lifecycle test (ephemeral uploads; does not touch seed state)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Production-style run: concurrency + fresh pipeline timing + mutations",
    )
    args = parser.parse_args()

    if args.full:
        args.with_concurrency = True
        args.with_pipeline_speed = True
        args.with_mutations = True

    ensure_reports_dir()
    results: dict[str, int] = {}

    for name, script_args in GATE_SCRIPTS + INFO_SCRIPTS + PERF_SCRIPTS:
        code = run_script(name, script_args)
        results[name] = code

    if args.with_concurrency:
        code = run_script("concurrency", ["compare_concurrency.py", "--workers", "3", "--wait"])
        results["concurrency"] = code

    if args.with_pipeline_speed:
        code = run_script(
            "speed_pipeline",
            ["compare_speed.py", "--pipeline", "--fresh-pipeline", "--rounds", "5"],
        )
        results["speed_pipeline"] = code

    if args.with_mutations:
        code = run_script("mutations", ["compare_mutations.py"])
        results["mutations"] = code

    if args.full:
        code = run_script("recompute", ["demo_recompute.py"])
        results["recompute"] = code

    gate_names = {name for name, _ in GATE_SCRIPTS} | {"observability", "data", "speed"}
    if args.with_concurrency:
        gate_names.add("concurrency")
    if args.with_pipeline_speed:
        gate_names.add("speed_pipeline")
    if args.with_mutations:
        gate_names.add("mutations")
    if args.full:
        gate_names.add("recompute")

    gates = {name: results.get(name, 1) for name in gate_names if name in results}
    gates_passed = all(code == 0 for code in gates.values())

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exit_codes": results,
        "gates": gates,
        "gates_passed": gates_passed,
        "reports_dir": str(ROOT / "compare" / "reports"),
    }
    path = write_report("summary", summary)

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for name, code in results.items():
        tag = " [gate]" if name in gate_names else " [info]"
        print(f"  {name}{tag}: {'OK' if code == 0 else f'FAIL ({code})'}")
    print(f"\nGates passed: {'YES' if gates_passed else 'NO'}")
    print(f"Combined summary: {path}")
    return 0 if gates_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
