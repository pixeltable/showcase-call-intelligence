#!/usr/bin/env python3
"""Reset both backends and upload shared compare fixtures."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.pxt_api import upload_pixeltable_fixture, wait_for_pixeltable_call
FIXTURES = ROOT / "compare" / "fixtures"
MANIFEST = FIXTURES / "manifest.json"
STATE_FILE = ROOT / ".compare-state.json"
REF_UPLOADS = Path(os.getenv("UPLOAD_DIR", str(ROOT / "data" / "reference" / "uploads")))
REF_API = os.getenv("REF_API", "http://127.0.0.1:8001")
PXT_API = os.getenv("PXT_API", "http://127.0.0.1:8000")


def _api_port(base_url: str, default: int) -> int:
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    if parsed.port:
        return parsed.port
    return default
POLL_SEC = 5
# Client-side poll cap while seeding (not Celery/Ollama limits). Increase on slow machines:
# TIMEOUT_SEC=1800 ./scripts/run_compare.sh seed
TIMEOUT_SEC = int(os.getenv("TIMEOUT_SEC", "1800"))
UPLOAD_TIMEOUT_SEC = float(os.getenv("UPLOAD_TIMEOUT_SEC", "30"))
POLL_TIMEOUT_SEC = float(os.getenv("POLL_TIMEOUT_SEC", "120"))

MIME_BY_EXT = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
}


def clear_reference_uploads() -> None:
    if REF_UPLOADS.is_dir():
        shutil.rmtree(REF_UPLOADS)
    REF_UPLOADS.mkdir(parents=True, exist_ok=True)
    print(f"Cleared reference uploads: {REF_UPLOADS}")


def reset_reference_db() -> None:
    ref_dir = ROOT / "backends" / "reference"
    script = """
from sqlalchemy import text
from app.database import engine
with engine.begin() as conn:
    conn.execute(text(
        "TRUNCATE TABLE coaching_comments, transcript_segments, calls RESTART IDENTITY CASCADE"
    ))
print("Reference Postgres truncated.")
"""
    subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=ref_dir,
        check=True,
    )


def reset_pixeltable_schema() -> None:
    pxt_port = _api_port(PXT_API, 8000)
    if os.getenv("COMPARE_FORCE_PORTS", "").lower() in ("1", "true", "yes"):
        subprocess.run(
            ["sh", "-c", f"lsof -ti:{pxt_port} | xargs kill -9 2>/dev/null || true"],
            check=False,
        )
    pxt_dir = ROOT / "backends" / "pixeltable"
    env = os.environ.copy()
    env.setdefault("PIXELTABLE_HOME", str(ROOT / "data" / "pixeltable"))
    env["RESET_SCHEMA"] = "true"
    subprocess.run(
        ["uv", "run", "python", "schema.py"],
        cwd=pxt_dir,
        env=env,
        check=True,
    )
    print("Pixeltable schema reset.")


def restart_pixeltable_api() -> None:
    pid_file = ROOT / ".compare-pids" / "pxt-api.pid"
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text().strip())
            if pid > 0:
                subprocess.run(["kill", str(pid)], check=False, stderr=subprocess.DEVNULL)
        except ValueError:
            pass
        pid_file.unlink(missing_ok=True)
    pxt_port = _api_port(PXT_API, 8000)
    if os.getenv("COMPARE_FORCE_PORTS", "").lower() in ("1", "true", "yes"):
        subprocess.run(
            ["sh", "-c", f"lsof -ti:{pxt_port} | xargs kill -9 2>/dev/null || true"],
            check=False,
        )
    pxt_dir = ROOT / "backends" / "pixeltable"
    restart_env = os.environ.copy()
    restart_env.setdefault("PIXELTABLE_HOME", str(ROOT / "data" / "pixeltable"))
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(pxt_port)],
        cwd=pxt_dir,
        env=restart_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid) + "\n")
    deadline = time.time() + 30
    with httpx.Client(timeout=5.0) as client:
        while time.time() < deadline:
            try:
                if client.get(f"{PXT_API}/api/health").status_code == 200:
                    print(f"Pixeltable API restarted (pid {proc.pid}).")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise RuntimeError("Pixeltable API did not become healthy after restart")


def upload_fixture(client: httpx.Client, base_url: str, entry: dict) -> str:
    path = FIXTURES / entry["file"]
    if not path.is_file():
        raise FileNotFoundError(path)
    mime = MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
    if base_url.rstrip("/") == PXT_API.rstrip("/"):
        return upload_pixeltable_fixture(
            client,
            base_url,
            path=path,
            entry=entry,
            mime=mime,
            timeout=UPLOAD_TIMEOUT_SEC,
        )
    with path.open("rb") as handle:
        resp = client.post(
            f"{base_url}/api/calls/upload",
            data={
                "call_date": entry["call_date"],
                "agent_id": entry["agent_id"],
                "customer_id": entry["customer_id"],
                "queue": entry["queue"],
                "vertical": entry.get("vertical", "call_center"),
            },
            files={"audio": (path.name, handle, mime)},
            timeout=UPLOAD_TIMEOUT_SEC,
        )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Upload failed ({base_url}): {resp.status_code} {resp.text}")
    call_id = resp.json().get("id")
    if not call_id:
        raise RuntimeError(f"Upload missing id from {base_url}")
    return str(call_id)


def wait_for_call(client: httpx.Client, base_url: str, call_id: str) -> dict:
    if base_url.rstrip("/") == PXT_API.rstrip("/"):
        return wait_for_pixeltable_call(
            client,
            base_url,
            call_id,
            poll_sec=POLL_SEC,
            timeout_sec=TIMEOUT_SEC,
        )
    deadline = time.time() + TIMEOUT_SEC
    while time.time() < deadline:
        resp = client.get(f"{base_url}/api/calls/{call_id}")
        if resp.status_code != 200:
            time.sleep(POLL_SEC)
            continue
        call = resp.json()
        status = call.get("status")
        print(f"  {base_url} {call_id[:8]}… status={status}")
        if status in {"completed", "failed"}:
            return call
        time.sleep(POLL_SEC)
    raise TimeoutError(f"Timed out waiting for {call_id} on {base_url}")


def ensure_semantic_search_ready() -> None:
    """Backfill reference segment vectors when embed model is available."""
    with httpx.Client(timeout=10.0) as client:
        try:
            health = client.get(f"{REF_API}/api/health")
            if health.status_code != 200:
                return
            embed = health.json().get("checks", {}).get("embed_model", {})
            if not embed.get("ok"):
                print(f"[WARN] Semantic search may be unavailable: {embed.get('detail')}")
                print("       First embed pass downloads EMBED_MODEL from Hugging Face Hub.")
                return
        except httpx.HTTPError:
            return

    ref_dir = ROOT / "backends" / "reference"
    script = """
from worker.tasks.embed_maintenance import backfill_embeddings
updated = backfill_embeddings(limit=500)
print(f"Backfilled {updated} reference segment embedding(s).")
"""
    subprocess.run(["uv", "run", "python", "-c", script], cwd=ref_dir, check=True)


def main() -> int:
    if not MANIFEST.is_file():
        print(f"Missing manifest: {MANIFEST}")
        return 1

    print("Generating synthetic fixture audio (if missing)…")
    gen = subprocess.run(
        ["uv", "run", "python", str(ROOT / "scripts" / "generate_fixture_audio.py")],
        cwd=ROOT,
        check=False,
    )
    if gen.returncode != 0:
        print("Fixture audio generation failed.")
        return gen.returncode

    print("Fetching fixture media…")
    fetch = subprocess.run(
        ["uv", "run", "python", str(ROOT / "scripts" / "fetch_fixtures.py")],
        cwd=ROOT,
        check=False,
    )
    if fetch.returncode != 0:
        print("Fixture fetch failed. Fix missing media before seeding.")
        return fetch.returncode

    print("Preparing derived fixture media…")
    prepare = subprocess.run(
        ["uv", "run", "python", str(ROOT / "scripts" / "prepare_fixture_media.py")],
        cwd=ROOT,
        check=False,
    )
    if prepare.returncode != 0:
        print("Derived fixture preparation failed.")
        return prepare.returncode

    print("Validating fixture manifest…")
    validate = subprocess.run(
        ["uv", "run", "python", str(ROOT / "scripts" / "validate_fixture_manifest.py")],
        cwd=ROOT,
        check=False,
    )
    if validate.returncode != 0:
        print("Fixture manifest validation failed.")
        return validate.returncode

    entries = json.loads(MANIFEST.read_text())
    print("Resetting reference database…")
    reset_reference_db()
    print("Clearing reference upload files…")
    clear_reference_uploads()
    print("Resetting Pixeltable schema…")
    reset_pixeltable_schema()
    print("Restarting Pixeltable API after schema reset…")
    restart_pixeltable_api()

    state: dict[str, dict[str, str]] = {}
    with httpx.Client(timeout=UPLOAD_TIMEOUT_SEC) as ref_client, httpx.Client(timeout=POLL_TIMEOUT_SEC) as pxt_client:
        for entry in entries:
            name = entry["file"]
            vertical = entry.get("vertical", "call_center")
            media_type = entry.get("media_type", "audio")
            print(f"Uploading {name} (vertical={vertical}, media={media_type})…")
            ref_id = upload_fixture(ref_client, REF_API, entry)
            pxt_id = upload_fixture(pxt_client, PXT_API, entry)
            state[name] = {"ref_id": ref_id, "pxt_id": pxt_id}

        print("Waiting for reference pipeline…")
        for entry in entries:
            wait_for_call(ref_client, REF_API, state[entry["file"]]["ref_id"])

        print("Waiting for Pixeltable pipeline…")
        for entry in entries:
            wait_for_call(pxt_client, PXT_API, state[entry["file"]]["pxt_id"])

    print("Checking semantic search prerequisites…")
    ensure_semantic_search_ready()

    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Wrote {STATE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
