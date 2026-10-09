"""Protocol errors must stop a benchmark, and dirty application changes must remain distinguishable."""

import subprocess
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark import source_fingerprint  # noqa: E402
from lib import client  # noqa: E402


def response(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://ollama/api/generate"))


def test_failed_cache_unload_stops_measurement(monkeypatch) -> None:
    monkeypatch.setattr(client.httpx, "post", lambda *args, **kwargs: response(500, {"error": "model runner failed"}))
    with pytest.raises(httpx.HTTPStatusError):
        client.reset_llm("http://ollama", "llama3.1")


def test_cache_unload_timeout_stops_measurement(monkeypatch) -> None:
    stamps = iter([0.0, 121.0])
    monkeypatch.setattr(client.time, "monotonic", lambda: next(stamps))
    monkeypatch.setattr(client.httpx, "post", lambda *args, **kwargs: response(200, {}))
    with pytest.raises(TimeoutError, match="reused prompt cache"):
        client.reset_llm("http://ollama", "llama3.1")


def test_cache_reset_loads_the_exact_tag_and_checks_readiness(monkeypatch) -> None:
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return response(200 if len(calls) == 1 else 500, {})
    monkeypatch.setattr(client.httpx, "post", post)
    monkeypatch.setattr(client.httpx, "get", lambda *args, **kwargs: response(200, {"models": [{"name": "llama3.1:other"}]}))
    with pytest.raises(httpx.HTTPStatusError):
        client.reset_llm("http://ollama", "llama3.1:latest")
    assert calls == [{"model": "llama3.1:latest", "keep_alive": 0},
                     {"model": "llama3.1:latest", "prompt": "", "stream": False}]


def test_source_fingerprint_includes_dirty_and_new_code_but_excludes_secrets(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "backends").mkdir()
    source = tmp_path / "backends" / "app.py"
    source.write_text("version = 1\n")
    initial = source_fingerprint(tmp_path)
    source.write_text("version = 2\n")
    assert source_fingerprint(tmp_path) != initial
    current = source_fingerprint(tmp_path)
    (tmp_path / ".env").write_text("TOKEN=not-a-real-token\n")
    assert source_fingerprint(tmp_path) == current
