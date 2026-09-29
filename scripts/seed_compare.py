#!/usr/bin/env python3
"""Reset both backends and ingest the fixture manifest into each. Writes .compare-state.json.

Run through ./scripts/run_compare.sh seed, which exports the ports, data paths and PXT_PORT.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.client import FIXTURES, backends, load_manifest, reset_llm  # noqa: E402

STATE_FILE = ROOT / ".compare-state.json"
PXT_DIR = ROOT / "backends" / "pixeltable"
REF_DIR = ROOT / "backends" / "reference"
TIMEOUT_SEC = float(os.getenv("TIMEOUT_SEC", "1800"))
FIXTURE_TOOLS = ["generate_fixture_audio.py", "fetch_fixtures.py", "prepare_fixture_media.py", "validate_fixture_manifest.py"]


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def pxt(*args: str) -> None:
    run(["uv", "run", "--quiet", "pxt", *args], PXT_DIR)


def clear_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def reset_reference() -> None:
    sql = "TRUNCATE TABLE coaching_comments, transcript_segments, calls CASCADE"
    script = f"from sqlalchemy import text\nfrom app.database import engine\nwith engine.begin() as c: c.execute(text({sql!r}))"
    run(["uv", "run", "python", "-c", script], REF_DIR)
    clear_dir(Path(os.environ["UPLOAD_DIR"]))


def reset_pixeltable() -> None:
    subprocess.run(["uv", "run", "--quiet", "pxt", "service", "stop", "call_center/api"], cwd=PXT_DIR, check=False)
    subprocess.run(["uv", "run", "--quiet", "pxt", "drop-dir", "call_center", "-r", "-f"], cwd=PXT_DIR, check=False)
    clear_dir(Path(os.environ["PXT_UPLOAD_DIR"]))
    pxt("schema", "update", "app.py", "call_center", "-f")
    pxt("service", "update", "app.py", "call_center", "--port", os.environ.get("PXT_API_PORT", "8000"), "-f")


def ingest(api, entries: list[dict]) -> dict[str, str]:
    ids = {}
    for e in entries:
        reset_llm()
        ids[e["file"]] = api.upload(FIXTURES / e["file"], e)
        call = api.wait(ids[e["file"]], timeout_sec=TIMEOUT_SEC).call
        print(f"  {api.name:<10} {e['file']:<30} {call['status']}", flush=True)
    return ids


def main() -> int:
    for tool in FIXTURE_TOOLS:
        run(["uv", "run", "python", str(ROOT / "scripts" / tool)], ROOT)
    reset_reference()
    reset_pixeltable()

    entries = load_manifest()  # fresh dates, identical on both backends
    ref, pxt_api = backends()
    for api in (ref, pxt_api):
        deadline, health = time.time() + 120, None
        while time.time() < deadline:
            try:
                health = api.health()
                if health["status"] == "ok":
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise SystemExit(f"{api.name} is not healthy, refusing to seed: {health}")

    # One call at a time, Ollama reloaded before each: two in-flight requests, or a prompt cache
    # left to grow over many calls, push a memory-bound Ollama (Docker Desktop's default VM) into
    # an out-of-memory restart.
    print(f"Ingesting {len(entries)} fixtures into each backend, one call at a time...", flush=True)
    ref_ids, pxt_ids = ingest(ref, entries), ingest(pxt_api, entries)
    state = {name: {"ref_id": ref_ids[name], "pxt_id": pxt_ids[name]} for name in ref_ids}
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Wrote {STATE_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
