#!/usr/bin/env python3
"""Lines-of-code comparison for backend surface area."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import PIXELTABLE, REFERENCE, count_loc, print_section, print_table, write_report

BUCKETS: dict[str, tuple[list[str], list[str], list[str] | None]] = {
    "api_routers": (
        ["app/routers/**/*.py"],
        ["routers/**/*.py"],
        None,
    ),
    "shared_schemas": (
        [],
        [],
        ["call_center_api/**/*.py"],
    ),
    "pipeline": (
        ["worker/**/*.py", "app/services/**/*.py"],
        ["functions.py", "schema.py"],
        None,
    ),
}


def main() -> int:
    print_section("Lines of Code (approximate, excl. .venv/node_modules)")
    rows = []
    report: dict[str, dict] = {}
    ref_total = 0
    pxt_total = 0

    for name, (ref_patterns, pxt_patterns, shared_patterns) in BUCKETS.items():
        ref = count_loc(REFERENCE.code_dir, ref_patterns) if ref_patterns else {"files": 0, "lines": 0}
        pxt = count_loc(PIXELTABLE.code_dir, pxt_patterns) if pxt_patterns else {"files": 0, "lines": 0}
        if shared_patterns:
            shared = count_loc(ROOT / "shared", shared_patterns)
            ref = {"files": ref["files"] + shared["files"], "lines": ref["lines"] + shared["lines"]}
            pxt = {"files": pxt["files"] + shared["files"], "lines": pxt["lines"] + shared["lines"]}
            report[name] = {"reference": ref, "pixeltable": pxt, "shared": shared}
        else:
            report[name] = {"reference": ref, "pixeltable": pxt}
        ref_total += ref["lines"]
        pxt_total += pxt["lines"]
        rows.append([name, ref["files"], ref["lines"], pxt["files"], pxt["lines"]])

    ui = count_loc(ROOT / "frontend" / "src", ["**/*.tsx", "**/*.ts"])
    rows.append(["frontend_ui (shared)", ui["files"], ui["lines"], ui["files"], ui["lines"]])
    report["frontend_ui"] = {"shared": ui}

    print_table(["Area", "Ref files", "Ref lines", "Pxt files", "Pxt lines"], rows)
    print(f"\nBackend total: reference={ref_total} lines, pixeltable={pxt_total} lines")
    ratio = round(ref_total / pxt_total, 2) if pxt_total else None
    if ratio:
        print(f"Reference / Pixeltable ratio: {ratio}x")

    path = write_report(
        "loc",
        {
            "buckets": report,
            "backend_total_lines": {"reference": ref_total, "pixeltable": pxt_total, "ratio": ratio},
        },
    )
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
