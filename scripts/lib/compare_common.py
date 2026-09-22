"""Shared helpers for side-by-side backend comparison scripts."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
REF_DIR = ROOT / "backends" / "reference"
PXT_DIR = ROOT / "backends" / "pixeltable"
FIXTURES = ROOT / "compare" / "fixtures"
STATE_FILE = ROOT / ".compare-state.json"
REPORTS_DIR = ROOT / "compare" / "reports"

REF_API = os.getenv("REF_API", "http://127.0.0.1:8001")
PXT_API = os.getenv("PXT_API", "http://127.0.0.1:8000")
UPLOAD_TIMEOUT_SEC = float(os.getenv("UPLOAD_TIMEOUT_SEC", "30"))


@dataclass
class Backend:
    name: str
    api: str
    code_dir: Path
    stack: str


REFERENCE = Backend("reference", REF_API, REF_DIR, "Celery + Postgres + pgvector")
PIXELTABLE = Backend("pixeltable", PXT_API, PXT_DIR, "Pixeltable computed columns")


def ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def load_state() -> dict[str, dict[str, str]]:
    if not STATE_FILE.is_file():
        return {}
    return json.loads(STATE_FILE.read_text())


def check_health(client: httpx.Client, backend: Backend) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        resp = client.get(f"{backend.api}/api/health")
        elapsed_ms = (time.perf_counter() - started) * 1000
        body: dict[str, Any] = resp.json() if resp.status_code == 200 else {}
        status = body.get("status", "unknown")
        checks = body.get("checks") or {}
        failed_checks = [
            name for name, check in checks.items() if isinstance(check, dict) and not check.get("ok", True)
        ]
        return {
            "ok": resp.status_code == 200,
            "status": status,
            "degraded": status == "degraded",
            "status_code": resp.status_code,
            "latency_ms": round(elapsed_ms, 2),
            "checks": checks,
            "failed_checks": failed_checks,
            "body": body if resp.status_code == 200 else resp.text[:200],
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc), "latency_ms": None}


def format_health_checks(checks: dict[str, Any]) -> str:
    if not checks:
        return "-"
    parts = []
    for name, check in sorted(checks.items()):
        if not isinstance(check, dict):
            continue
        mark = "OK" if check.get("ok") else "FAIL"
        detail = check.get("detail") or check.get("home") or ""
        parts.append(f"{name}={mark}" + (f" ({detail})" if detail else ""))
    return "; ".join(parts) if parts else "-"


def timed_request(client: httpx.Client, method: str, url: str, **kwargs) -> dict[str, Any]:
    started = time.perf_counter()
    resp = client.request(method, url, **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "status_code": resp.status_code,
        "latency_ms": round(elapsed_ms, 2),
        "ok": resp.status_code < 400,
    }


def count_loc(root: Path, globs: list[str], *, exclude: set[str] | None = None) -> dict[str, int]:
    exclude = exclude or {".venv", "node_modules", "__pycache__", "dist"}
    files: list[Path] = []
    for pattern in globs:
        files.extend(root.glob(pattern))
    unique = []
    seen: set[Path] = set()
    for path in files:
        if any(part in exclude for part in path.parts):
            continue
        if path.is_file() and path not in seen:
            seen.add(path)
            unique.append(path)
    lines = 0
    for path in unique:
        try:
            lines += sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return {"files": len(unique), "lines": lines}


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def print_table(headers: list[str], rows: list[list[Any]]) -> None:
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def write_report(name: str, payload: dict[str, Any]) -> Path:
    out_dir = ensure_reports_dir()
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return path


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

POLL_SEC = 5
PIPELINE_TIMEOUT_SEC = 600


def upload_fixture(
    client: httpx.Client,
    backend: Backend,
    fixture_path: Path,
    meta: dict,
    *,
    agent_suffix: str = "",
) -> str:
    mime = MIME_BY_EXT.get(fixture_path.suffix.lower(), "application/octet-stream")
    agent_id = meta["agent_id"]
    if agent_suffix:
        agent_id = f"{agent_id}-{agent_suffix}"
    if backend.name == "pixeltable":
        from lib.pxt_api import upload_pixeltable_fixture

        entry = {**meta, "agent_id": agent_id}
        return upload_pixeltable_fixture(
            client,
            backend.api,
            path=fixture_path,
            entry=entry,
            mime=mime,
            timeout=UPLOAD_TIMEOUT_SEC,
        )
    with fixture_path.open("rb") as handle:
        resp = client.post(
            f"{backend.api}/api/calls/upload",
            data={
                "call_date": meta["call_date"],
                "agent_id": agent_id,
                "customer_id": meta["customer_id"],
                "queue": meta["queue"],
            },
            files={"audio": (fixture_path.name, handle, mime)},
            timeout=UPLOAD_TIMEOUT_SEC,
        )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Upload failed ({backend.name}): {resp.status_code} {resp.text}")
    call_id = resp.json().get("id")
    if not call_id:
        raise RuntimeError(f"Upload missing id from {backend.name}")
    return str(call_id)


def wait_for_call(
    client: httpx.Client,
    backend: Backend,
    call_id: str,
    *,
    timeout_sec: float = PIPELINE_TIMEOUT_SEC,
) -> dict:
    if backend.name == "pixeltable":
        from lib.pxt_api import wait_for_pixeltable_call

        return wait_for_pixeltable_call(
            client,
            backend.api,
            call_id,
            poll_sec=POLL_SEC,
            timeout_sec=timeout_sec,
        )
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        resp = client.get(f"{backend.api}/api/calls/{call_id}")
        if resp.status_code == 200:
            call = resp.json()
            if call.get("status") in {"completed", "failed"}:
                return call
        time.sleep(POLL_SEC)
    raise TimeoutError(f"Timed out waiting for {call_id} on {backend.name}")


def upload_and_wait(
    client: httpx.Client,
    backend: Backend,
    fixture_path: Path,
    meta: dict,
    *,
    agent_suffix: str = "",
) -> dict:
    call_id = upload_fixture(client, backend, fixture_path, meta, agent_suffix=agent_suffix)
    call = wait_for_call(client, backend, call_id)
    if call.get("status") != "completed":
        raise RuntimeError(f"{backend.name} call {call_id} ended with status={call.get('status')}")
    return call


def post_comment(client: httpx.Client, backend: Backend, payload: dict) -> dict:
    body = dict(payload)
    if backend.name == "pixeltable":
        from lib.pxt_api import segment_uuid
        import uuid as _uuid

        call_id = body.pop("call_id", None) or body.get("call_uuid")
        body["call_uuid"] = str(call_id)
        segment_id = body.pop("segment_id", None)
        segment_pos = body.get("segment_pos", -1)
        if segment_id is not None and call_id is not None:
            for pos in range(256):
                if segment_uuid(_uuid.UUID(str(call_id)), pos) == _uuid.UUID(str(segment_id)):
                    segment_pos = pos
                    break
        body["segment_pos"] = segment_pos
    resp = client.post(f"{backend.api}/api/comments", json=body, timeout=30.0)
    if resp.status_code != 201:
        raise RuntimeError(f"Comment failed ({backend.name}): {resp.status_code} {resp.text}")
    data = resp.json()
    if backend.name == "pixeltable":
        data["id"] = data.get("uuid")
    return data


def delete_call(client: httpx.Client, backend: Backend, call_id: str) -> int:
    resp = client.delete(f"{backend.api}/api/calls/{call_id}", timeout=30.0)
    return resp.status_code


def reference_call_stats(call_id: str) -> dict[str, Any]:
    script = f"""
import json
from pathlib import Path
from sqlalchemy import text
from app.database import engine

call_id = "{call_id}"
audio_path = None
video_path = None
with engine.connect() as conn:
    segments = conn.execute(
        text("SELECT COUNT(*) FROM transcript_segments WHERE call_id = :id"),
        {{"id": call_id}},
    ).scalar()
    comments = conn.execute(
        text("SELECT COUNT(*) FROM coaching_comments WHERE call_id = :id"),
        {{"id": call_id}},
    ).scalar()
    row = conn.execute(
        text("SELECT audio_path, video_path FROM calls WHERE id = :id"),
        {{"id": call_id}},
    ).first()
    if row:
        audio_path, video_path = row[0], row[1]

print(json.dumps({{
    "segments": int(segments or 0),
    "comments": int(comments or 0),
    "call_exists": row is not None,
    "audio_path": audio_path,
    "video_path": video_path,
    "audio_exists": bool(audio_path and Path(audio_path).is_file()),
    "video_exists": bool(video_path and Path(video_path).is_file()),
}}))
"""
    result = _run_backend_script(REFERENCE.code_dir, script)
    return result


def pixeltable_call_stats(call_id: str) -> dict[str, Any]:
    script = f"""
import json
import pixeltable as pxt

call_id = "{call_id}"
out = {{"call_rows": 0, "comment_rows": 0, "view_segment_rows": 0}}
try:
    calls = pxt.get_table("call_center.calls")
    out["call_rows"] = int(calls.where(calls.uuid == call_id).count())
    comments = pxt.get_table("call_center.coaching_comments")
    out["comment_rows"] = int(comments.where(comments.call_uuid == call_id).count())
    try:
        segments = pxt.get_table("call_center.transcript_segments")
        out["view_segment_rows"] = int(segments.where(segments.uuid == call_id).count())
    except Exception:
        out["view_segment_rows"] = None
except Exception as exc:
    out["error"] = str(exc)
print(json.dumps(out))
"""
    env = os.environ.copy()
    env.setdefault("PIXELTABLE_HOME", str(ROOT / "data" / "pixeltable"))
    result = _run_backend_script(PXT_DIR, script, env=env)
    return result


def _run_backend_script(code_dir: Path, script: str, *, env: dict | None = None) -> dict[str, Any]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    result = subprocess.run(
        ["uv", "run", "python", "-c", script],
        cwd=code_dir,
        env=run_env,
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
