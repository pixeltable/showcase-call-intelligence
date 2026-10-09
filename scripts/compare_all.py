#!/usr/bin/env python3
"""Run the correctness gates against both running backends. Exit 0 only if every gate passes.

    uv run python scripts/compare_all.py            # parity on the seeded fixtures + mutations
    uv run python scripts/compare_all.py --parity   # parity only (no uploads)

Timings are not gates: they come from scripts/benchmark.py and land in compare/results/.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = {"parity": "compare_parity.py", "mutations": "compare_mutations.py"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parity", action="store_true", help="Skip the mutation gate, which uploads a call")
    args = parser.parse_args()
    results = {}
    for name, script in GATES.items():
        if args.parity and name != "parity":
            continue
        print(f"\n=== {name} ===")
        results[name] = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT).returncode
    print("\n" + "\n".join(f"  {name}: {'PASS' if code == 0 else 'FAIL'}" for name, code in results.items()))
    return 0 if all(code == 0 for code in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
