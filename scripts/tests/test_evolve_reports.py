"""Evolution runs cannot relabel historical successes or overwrite another invocation."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bench_evolve as evolve  # noqa: E402


@pytest.fixture
def reports(monkeypatch, tmp_path):
    published = evolve.ROOT / "compare" / "results" / "evolve.json"
    original = published.read_bytes()
    monkeypatch.setattr(evolve, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(evolve, "setup_provenance", lambda: {"identity": "current-source", "environment": {"pixeltable": "0.7.15"}})
    monkeypatch.setattr(evolve, "add_field", lambda: {"new_measurement": 1})
    monkeypatch.setattr(evolve, "rerun_step", lambda full: {"new_measurement": 2})
    monkeypatch.setattr(evolve, "recover_failed_step", lambda: {"new_measurement": 3})
    yield tmp_path
    assert published.read_bytes() == original


def test_partial_run_has_only_current_selected_experiment(reports):
    assert evolve.main(["--only", "rerun_step"]) == 0
    report = json.loads(next(reports.glob("*.json")).read_text())
    assert report["status"] == "succeeded"
    assert set(report["experiments"]) == {"rerun_step"}
    assert report["experiments"]["rerun_step"]["setup_identity"] == "current-source"
    assert report["experiments"]["rerun_step"]["result"] == {"new_measurement": 2}


def test_failed_experiment_does_not_retain_an_old_success(reports, monkeypatch):
    def fail():
        raise RuntimeError("fixture failure")
    monkeypatch.setattr(evolve, "add_field", fail)
    assert evolve.main([]) == 1
    report = json.loads(next(reports.glob("*.json")).read_text())
    entry = report["experiments"]["add_field"]
    assert report["status"] == entry["status"] == "failed"
    assert entry["error"] == "RuntimeError: fixture failure"
    assert "result" not in entry
    assert report["experiments"]["recover"]["status"] == "succeeded"


def test_existing_output_is_refused_before_checks_or_experiments(reports, monkeypatch):
    output = reports / "existing.json"
    output.write_text("keep these bytes")
    def forbidden():
        pytest.fail("Provider checks or experiment ran before output collision was rejected")
    monkeypatch.setattr(evolve, "setup_provenance", forbidden)
    monkeypatch.setattr(evolve, "add_field", forbidden)
    with pytest.raises(SystemExit) as exc:
        evolve.main(["--output", str(output)])
    assert exc.value.code == 2
    assert output.read_text() == "keep these bytes"


def test_consecutive_invocations_are_distinct_even_at_the_same_time(reports, monkeypatch):
    monkeypatch.setattr(evolve, "timestamp", lambda: "2026-10-09T00:00:00+00:00")
    assert evolve.main(["--only", "recover"]) == evolve.main(["--only", "recover"]) == 0
    records = [json.loads(path.read_text()) for path in reports.glob("*.json")]
    assert len(records) == 2
    assert len({record["run_id"] for record in records}) == 2


def test_provenance_failure_is_recorded_without_running_experiments(reports, monkeypatch):
    def fail():
        raise ValueError("missing fixture")
    monkeypatch.setattr(evolve, "setup_provenance", fail)
    assert evolve.main([]) == 1
    report = json.loads(next(reports.glob("*.json")).read_text())
    assert report["status"] == "failed"
    assert report["error"] == "ValueError: missing fixture"
    assert report["experiments"] == {}


def test_interrupted_run_has_an_explicit_status(reports, monkeypatch):
    def interrupt():
        raise KeyboardInterrupt()
    monkeypatch.setattr(evolve, "add_field", interrupt)
    assert evolve.main([]) == 130
    report = json.loads(next(reports.glob("*.json")).read_text())
    assert report["status"] == report["experiments"]["add_field"]["status"] == "interrupted"
    assert "result" not in report["experiments"]["add_field"]


def test_provenance_includes_source_models_fixture_bytes_and_patches(monkeypatch, tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    media = fixtures / "short.wav"
    media.write_bytes(b"fixture-audio")
    (fixtures / "manifest.json").write_text('[{"file": "short.wav"}]')
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "change.patch").write_text("original patch")
    state = tmp_path / "state.json"
    state.write_text('{"short.wav": {"pxt_id": "p", "ref_id": "r"}}')
    monkeypatch.setattr(evolve, "FIXTURES", fixtures)
    monkeypatch.setattr(evolve, "EVOLVE", patches)
    monkeypatch.setattr(evolve, "STATE_FILE", state)
    monkeypatch.setattr(evolve, "load_manifest", lambda **kwargs: [{"file": "short.wav"}])
    monkeypatch.setattr(evolve, "environment", lambda host, model: {"source_fingerprint": "source-a", "model": model})
    first = evolve.setup_provenance()
    assert first["environment"]["source_fingerprint"] == "source-a"
    assert "short.wav" in first["fixture_sha256"]
    assert "change.patch" in first["patch_sha256"]
    media.write_bytes(b"changed fixture")
    assert evolve.setup_provenance()["identity"] != first["identity"]
    current = evolve.setup_provenance()["identity"]
    monkeypatch.setenv("OLLAMA_MODEL", "another-model")
    assert evolve.setup_provenance()["identity"] != current
