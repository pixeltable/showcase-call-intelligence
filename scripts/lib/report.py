"""PASS/FAIL bookkeeping for the compare gates. Reports land in compare/reports/ (gitignored)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORTS = Path(__file__).resolve().parents[2] / "compare" / "reports"


class Checks:
    def __init__(self, gate: str) -> None:
        self.gate = gate
        self.results: list[dict[str, Any]] = []
        self.data: dict[str, Any] = {}

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"check": label, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
        return bool(ok)

    def record(self, key: str, value: Any) -> None:
        self.data[key] = value

    def report(self) -> dict[str, Any]:
        failed = [r for r in self.results if not r["ok"]]
        print(f"\n{self.gate}: {len(self.results) - len(failed)}/{len(self.results)} checks passed")
        return {"gate": self.gate, "passed": not failed, "failed": failed, "checks": self.results, "data": self.data}

    def exit_code(self) -> int:
        return 0 if all(r["ok"] for r in self.results) else 1


def write_report(name: str, payload: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{name}.json"
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), **payload}
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return path
