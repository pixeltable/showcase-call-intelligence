#!/usr/bin/env python3
"""Demonstrate Pixeltable incremental recompute vs reference full reprocess."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PXT_DIR = ROOT / "backends" / "pixeltable"


def main() -> int:
    env = os.environ.copy()
    env.setdefault("PIXELTABLE_HOME", str(ROOT / "data" / "pixeltable"))
    result = subprocess.run(
        ["uv", "run", "python", str(ROOT / "scripts" / "demo_recompute_inner.py")],
        cwd=PXT_DIR,
        env=env,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
