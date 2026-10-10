"""Each benchmark invocation records its own outcomes without reusing published timings."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import benchmark as bench  # noqa: E402


@pytest.fixture
def reports(monkeypatch, tmp_path):
    published = bench.ROOT / "compare" / "results" / "benchmarks.json"
    original = published.read_bytes()
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    entries = [{"file": "short.wav"}]
    (fixtures / "short.wav").write_bytes(b"fixture-audio")
    (fixtures / "manifest.json").write_text(json.dumps(entries))
    seed = tmp_path / "state.json"
    seed.write_text('{"short.wav": {"pxt_id": "p", "ref_id": "r"}}')
    output = tmp_path / "reports"
    monkeypatch.setattr(bench, "REPORT_DIR", output)
    monkeypatch.setattr(bench, "FIXTURES", fixtures)
    monkeypatch.setattr(bench, "STATE_FILE", seed)
    monkeypatch.setattr(bench, "load_manifest", lambda: entries)
    monkeypatch.setattr(bench, "environment", lambda host, model: {
        "source_fingerprint": "current-source", "packages": {"pixeltable": "0.7.16"}, "measured_at": "now",
    })
    monkeypatch.setattr(bench, "backends", lambda: (SimpleNamespace(name="reference"), SimpleNamespace(name="pixeltable")))
    monkeypatch.setattr(bench, "time_call", lambda *args: {
        "status": "completed", "error": None, "accept_sec": 0.01, "complete_sec": 1.0,
    })
    monkeypatch.setattr(bench, "time_reads", lambda *args: {"new endpoint": {"new_measurement": 1}})
    yield output
    assert published.read_bytes() == original


def report_at(output):
    return json.loads(next(output.glob("*.json")).read_text())


def test_existing_output_refused_before_provider_or_service_work(reports, monkeypatch):
    reports.mkdir()
    output = reports / "existing.json"
    output.write_text("preserve these bytes")

    def forbidden(*args, **kwargs):
        pytest.fail("Provider or service work started before output collision was rejected")

    for name in ("backends", "environment", "time_call", "time_reads", "load_manifest"):
        monkeypatch.setattr(bench, name, forbidden)
    with pytest.raises(SystemExit) as exc:
        bench.main(["--output", str(output)])
    assert exc.value.code == 2
    assert output.read_text() == "preserve these bytes"


@pytest.mark.parametrize("skip, measured, omitted", [
    ("--skip-pipeline", "reads", "pipeline"), ("--skip-reads", "pipeline", "reads"),
])
def test_partial_run_contains_only_current_measurement(reports, skip, measured, omitted):
    assert bench.main([skip, "--rounds", "1", "--reads", "1"]) == 0
    report = report_at(reports)
    assert report["status"] == "succeeded"
    assert report["requested_sections"] == [measured]
    assert set(report["sections"]) == {measured}
    assert omitted not in report and f"{omitted}_measured_at" not in report
    assert report["environment"]["source_fingerprint"] == "current-source"
    assert report["setup"]["identity"]


def test_terminal_failed_call_makes_run_fail_and_preserves_actual_outcomes(reports, monkeypatch):
    outcomes = iter(["completed", "completed", "failed", "completed"])
    monkeypatch.setattr(bench, "time_call", lambda *args: {
        "status": next(outcomes), "error": "provider failure", "complete_sec": 1.0,
    })
    assert bench.main(["--rounds", "1", "--reads", "1"]) == 1
    report = report_at(reports)
    assert report["status"] == report["sections"]["pipeline"]["status"] == "failed"
    assert report["sections"]["reads"]["status"] == "succeeded"
    assert report["pipeline"]["short.wav"]["reference"][0]["status"] == "failed"
    attempt = report["attempts"][2]
    assert attempt["status"] == "failed" and attempt["call_status"] == "failed"
    assert attempt["phase"] == "timed" and attempt["round"] == 1


def test_exception_records_the_attempt_and_retains_only_completed_current_samples(reports, monkeypatch):
    count = 0

    def measure(*args):
        nonlocal count
        count += 1
        if count == 4:
            raise TimeoutError("call did not become terminal")
        return {"status": "completed", "complete_sec": 1.0}

    monkeypatch.setattr(bench, "time_call", measure)
    assert bench.main(["--rounds", "1", "--reads", "1"]) == 1
    report = report_at(reports)
    assert report["status"] == report["sections"]["pipeline"]["status"] == "failed"
    assert report["attempts"][-1]["error"] == "TimeoutError: call did not become terminal"
    assert len(report["pipeline"]["short.wav"]["reference"]) == 1
    assert report["pipeline"]["short.wav"]["pixeltable"] == []
    assert "reads" not in report and "reads" not in report["sections"]


def test_interrupted_run_has_no_historical_success(reports, monkeypatch):
    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(bench, "time_call", interrupt)
    assert bench.main(["--skip-reads"]) == 130
    report = report_at(reports)
    assert report["status"] == report["sections"]["pipeline"]["status"] == "interrupted"
    assert report["attempts"][0]["status"] == "interrupted"
    assert "pipeline" not in report and report["first_call"] == {}


def test_provenance_failure_is_saved_before_any_measurement(reports, monkeypatch):
    def fail(*args):
        raise RuntimeError("model metadata unavailable")

    monkeypatch.setattr(bench, "environment", fail)
    monkeypatch.setattr(bench, "time_call", lambda *args: pytest.fail("Unexpected measurement"))
    assert bench.main(["--skip-reads"]) == 1
    report = report_at(reports)
    assert report["status"] == "failed" and report["sections"] == {} and report["attempts"] == []
    assert report["error"] == "RuntimeError: model metadata unavailable"


def test_read_failure_keeps_current_pipeline_and_marks_the_read_section_failed(reports, monkeypatch):
    def fail(*args):
        raise RuntimeError("reference /api/search: HTTP 503")

    monkeypatch.setattr(bench, "time_reads", fail)
    assert bench.main(["--rounds", "1", "--reads", "1"]) == 1
    report = report_at(reports)
    assert report["sections"]["pipeline"]["status"] == "succeeded"
    assert report["sections"]["reads"]["status"] == "failed"
    assert "HTTP 503" in report["sections"]["reads"]["error"]
    assert "reads" not in report


def test_consecutive_runs_are_distinct_even_with_identical_timestamps(reports, monkeypatch):
    monkeypatch.setattr(bench, "timestamp", lambda: "2026-10-09T00:00:00+00:00")
    assert bench.main(["--skip-pipeline", "--reads", "1"]) == 0
    assert bench.main(["--skip-pipeline", "--reads", "1"]) == 0
    records = [json.loads(path.read_text()) for path in reports.glob("*.json")]
    assert len(records) == 2 and len({r["run_id"] for r in records}) == 2


def test_setup_tracks_actual_fixture_and_seed_bytes(reports):
    entries = [{"file": "short.wav"}]
    first = bench.setup_provenance(entries, pipeline=True, reads=True)
    (bench.FIXTURES / "short.wav").write_bytes(b"different-audio")
    changed_media = bench.setup_provenance(entries, pipeline=True, reads=True)
    assert changed_media["fixture_sha256"] != first["fixture_sha256"]
    bench.STATE_FILE.write_text('{"different": "seed-state"}')
    assert bench.setup_provenance(entries, pipeline=True, reads=True)["seed_state_sha256"] != first["seed_state_sha256"]
    reads_only = bench.setup_provenance(entries, pipeline=False, reads=True)
    assert reads_only["fixture_sha256"] == {}
