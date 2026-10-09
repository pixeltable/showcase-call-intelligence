"""One HTTP client for both backends: they serve the same contract (shared/call_center_api/schemas.py).

The one wire difference: list routes that Pixeltable declares with `add_query_route` wrap rows
in `{"rows": [...]}`. `rows()` accepts either envelope.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "compare" / "fixtures"
MANIFEST = FIXTURES / "manifest.json"

TERMINAL = frozenset({"completed", "failed"})
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


def rows(body: Any) -> list[dict]:
    if isinstance(body, dict) and isinstance(body.get("rows"), list):
        return body["rows"]
    return body if isinstance(body, list) else []


def load_manifest(*, fresh_dates: bool = True) -> list[dict]:
    """Manifest entries. With fresh_dates, the newest call lands one hour ago and spacing is kept,
    so the 7-day KPI window sees every seeded call whenever the seed runs."""
    entries = json.loads(MANIFEST.read_text())
    if not fresh_dates:
        return entries
    stamps = [datetime.fromisoformat(e["call_date"].replace("Z", "+00:00")) for e in entries]
    shift = datetime.now(timezone.utc) - timedelta(hours=1) - max(stamps)
    return [{**e, "call_date": (s + shift).isoformat()} for e, s in zip(entries, stamps, strict=True)]


@dataclass
class Waited:
    call: dict
    elapsed_sec: float
    transitions: list[tuple[float, str]] = field(default_factory=list)


class Api:
    def __init__(self, name: str, base_url: str, *, timeout: float = 60.0) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout)

    def __repr__(self) -> str:
        return f"Api({self.name}, {self.base_url})"

    def close(self) -> None:
        self.http.close()

    def health(self) -> dict:
        resp = self.http.get("/api/health")
        resp.raise_for_status()
        return resp.json()

    def upload(self, path: Path, meta: dict, *, agent_suffix: str = "") -> str:
        agent_id = f"{meta['agent_id']}-{agent_suffix}" if agent_suffix else meta["agent_id"]
        mime = MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
        with path.open("rb") as handle:
            resp = self.http.post(
                "/api/calls/upload",
                data={
                    "call_date": meta["call_date"],
                    "agent_id": agent_id,
                    "customer_id": meta["customer_id"],
                    "queue": meta["queue"],
                    "vertical": meta.get("vertical", "call_center"),
                },
                files={"audio": (path.name, handle, mime)},
            )
        if resp.status_code != 202:
            raise RuntimeError(f"{self.name} upload {path.name}: HTTP {resp.status_code} {resp.text[:300]}")
        return str(resp.json()["id"])

    def detail(self, call_id: str) -> dict | None:
        resp = self.http.get(f"/api/calls/{call_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def wait(self, call_id: str, *, timeout_sec: float = 1800, poll_sec: float = 0.5) -> Waited:
        """Poll until the call is completed or failed. Records each status the API showed."""
        started = time.perf_counter()
        transitions: list[tuple[float, str]] = []
        while time.perf_counter() - started < timeout_sec:
            call = self.detail(call_id)
            status = (call or {}).get("status") or "not visible"
            if not transitions or transitions[-1][1] != status:
                transitions.append((round(time.perf_counter() - started, 2), status))
            if call and status in TERMINAL:
                return Waited(call, round(time.perf_counter() - started, 2), transitions)
            time.sleep(poll_sec)
        raise TimeoutError(f"{self.name} call {call_id} not terminal after {timeout_sec}s: {transitions}")

    def list_calls(self, **params: Any) -> list[dict]:
        resp = self.http.get("/api/calls", params={k: v for k, v in params.items() if v is not None})
        resp.raise_for_status()
        return rows(resp.json())

    def flagged(self) -> list[dict]:
        resp = self.http.get("/api/calls/flagged")
        resp.raise_for_status()
        return rows(resp.json())

    def kpis(self) -> dict:
        resp = self.http.get("/api/calls/kpis")
        resp.raise_for_status()
        return resp.json()

    def search(self, q: str, *, mode: str = "hybrid", limit: int = 20) -> list[dict]:
        resp = self.http.get("/api/search", params={"q": q, "mode": mode, "limit": limit})
        resp.raise_for_status()
        return rows(resp.json())

    def comment(self, call_id: str, *, segment_id: str | None, start_sec: float, author: str, text: str) -> dict:
        payload = {"call_id": call_id, "start_sec": start_sec, "author": author, "comment": text}
        if segment_id is not None:
            payload["segment_id"] = segment_id
        resp = self.http.post("/api/comments", json=payload)
        if resp.status_code != 201:
            raise RuntimeError(f"{self.name} comment: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def comments(self, call_id: str) -> list[dict]:
        resp = self.http.get(f"/api/comments/call/{call_id}")
        resp.raise_for_status()
        return rows(resp.json())

    def delete(self, call_id: str) -> int:
        return self.http.delete(f"/api/calls/{call_id}").status_code

    def media(self, call_id: str, kind: str) -> int:
        with self.http.stream("GET", f"/api/calls/{call_id}/{kind}") as resp:
            return resp.status_code


def reset_llm(host: str | None = None, model: str | None = None) -> None:
    """Reload the shared Ollama model so the next call starts with loaded weights and an empty prompt cache.

    Ollama's server caches the KV state of recent prompts. Both backends send byte-identical prompts
    for the same recording, so without a reset the second one to run gets cache hits the first did
    not, and the cache grows until the model runner is killed for memory.
    """
    host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    model = model or os.getenv("OLLAMA_MODEL", "llama3.1")
    required = model if ":" in model else f"{model}:latest"
    httpx.post(f"{host}/api/generate", json={"model": model, "keep_alive": 0}, timeout=120).raise_for_status()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = httpx.get(f"{host}/api/ps", timeout=10)
        response.raise_for_status()
        loaded = response.json().get("models", [])
        if not any(m["name"] == required for m in loaded):
            break
        time.sleep(0.5)
    else:
        raise TimeoutError(f"Ollama model {required} remained loaded; refusing to measure with a reused prompt cache")
    httpx.post(f"{host}/api/generate", json={"model": model, "prompt": "", "stream": False}, timeout=600).raise_for_status()


def backends() -> tuple[Api, Api]:
    """(reference, pixeltable) from REF_API / PXT_API."""
    return (
        Api("reference", os.getenv("REF_API", "http://127.0.0.1:8001")),
        Api("pixeltable", os.getenv("PXT_API", "http://127.0.0.1:8000")),
    )
