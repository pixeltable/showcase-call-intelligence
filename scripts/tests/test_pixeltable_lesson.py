"""The lesson owns its services and seeds a single fixture without resetting other data."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seed_pixeltable as seed  # noqa: E402


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "lesson"
    (root / "scripts").mkdir(parents=True)
    (root / "backends" / "pixeltable").mkdir(parents=True)
    script = root / "scripts" / "run_pixeltable.sh"
    shutil.copy(Path(__file__).resolve().parents[1] / "run_pixeltable.sh", script)
    tools = tmp_path / "tools"
    tools.mkdir()
    recorder = '''#!/usr/bin/env python3
import json, os, pathlib, sys
with pathlib.Path(os.environ['FIXTURE_LOG']).open('a') as output:
 output.write(json.dumps({'tool': pathlib.Path(sys.argv[0]).name, 'args': sys.argv[1:],
  'profile': os.getenv('PXT_ENRICHMENT_PROFILE'), 'home': os.getenv('PIXELTABLE_HOME')}) + '\\n')
if os.getenv('FIXTURE_PORT_COLLISION') and '-' in sys.argv:
 raise SystemExit(1)
'''
    for name in ("uv", "docker"):
        path = tools / name
        path.write_text(recorder)
        path.chmod(0o755)
    log = tmp_path / "commands.jsonl"
    env = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}", "FIXTURE_LOG": str(log), "NO_UI": "1"}
    def run(command, **extra):
        result = subprocess.run(["bash", str(script), command], env={**env, **extra}, capture_output=True, text=True)
        events = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, events
    return root, run


def test_lesson_starts_only_pixeltable_and_ollama_in_its_own_catalog(launcher):
    root, run = launcher
    result, events = run("up")
    assert result.returncode == 0, result.stderr
    assert [e["args"] for e in events if e["tool"] == "docker"] == [["compose", "up", "-d", "ollama"]]
    assert all(e["profile"] == "core" and e["home"] == str(root / "data/lesson/pixeltable") for e in events)
    assert any(e["args"] == ["run", "--frozen", "pxt", "service", "update", "app.py", "first_lesson", "--port", "8002", "-f"] for e in events)
    assert not any("call_center" in e["args"] or "celery" in e["args"] for e in events)


def test_occupied_daemon_port_stops_before_any_service_operation(launcher):
    _, run = launcher
    result, events = run("up", FIXTURE_PORT_COLLISION="1")
    assert result.returncode != 0
    assert len(events) == 1 and "-" in events[0]["args"]


def test_lesson_stop_targets_only_its_own_service_and_daemon(launcher):
    root, run = launcher
    home = root / "data/lesson/pixeltable"
    home.mkdir(parents=True)
    (home / "pxt-daemon-22091.pid").write_text("12345")
    result, events = run("stop")
    assert result.returncode == 0
    assert [e["args"][3:] for e in events] == [["service", "stop", "first_lesson/api"], ["daemon", "stop"]]
    assert all(e["tool"] == "uv" for e in events)


@pytest.fixture
def api(monkeypatch, tmp_path):
    class FixtureApi:
        upload_count = 0
        saved_call = None
        closed = False
        def detail(self, call_id):
            return self.saved_call
        def health(self):
            return {"status": "ok", "enrichment_profile": "core"}
        def upload(self, path, metadata):
            assert path.name == "billing-inquiry-speech.wav"
            self.upload_count += 1
            return "new-call"
        def wait(self, call_id):
            return SimpleNamespace(call={"status": "completed"})
        def close(self):
            self.closed = True
    instance = FixtureApi()
    monkeypatch.setattr(seed, "Api", lambda *args, **kwargs: instance)
    monkeypatch.setattr(seed, "STATE_FILE", tmp_path / "fixture.json")
    return instance


def test_seed_uploads_one_fixture_and_records_receipt(api):
    assert seed.main() == 0
    assert api.upload_count == 1 and api.closed
    assert json.loads(seed.STATE_FILE.read_text())["call_id"] == "new-call"


def test_seed_reuses_existing_call_without_upload_or_reset(api):
    seed.STATE_FILE.write_text('{"call_id": "saved-call"}')
    api.saved_call = {"id": "saved-call", "status": "completed"}
    assert seed.main() == 0
    assert api.upload_count == 0


def test_seed_refuses_full_profile_before_upload(api, monkeypatch):
    monkeypatch.setattr(api, "health", lambda: {"status": "ok", "enrichment_profile": "full"})
    with pytest.raises(RuntimeError, match="core lesson"):
        seed.main()
    assert api.upload_count == 0 and api.closed
