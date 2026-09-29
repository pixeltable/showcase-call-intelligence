"""A failed run stays visible in the published pipeline results, and a fixture that never completed renders."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import render_results  # noqa: E402


def run(sec: float, status: str = "completed") -> dict:
    return {"complete_sec": sec, "status": status, "accept_sec": 0.02, "transitions": [[0.0, "queued"], [sec, status]]}


BENCH = {
    "pipeline_rounds": 3,
    "environment": {"ollama": {"model": "llama3.1"}},
    "pipeline": {
        "partial.wav": {"reference": [run(10), run(12), run(11)], "pixeltable": [run(9), run(30, "failed"), run(10)]},
        "all-failed.wav": {"reference": [run(20), run(21), run(22)], "pixeltable": [run(5, "failed")] * 3},
    },
}


def test_medians_use_completed_runs_and_none_when_all_failed():
    med = render_results.pipeline_medians(BENCH)
    assert med["partial.wav"] == {"reference": 11, "pixeltable": 9.5}
    assert med["all-failed.wav"]["pixeltable"] is None


def test_table_names_failures_and_totals_only_what_both_completed():
    out = render_results.pipeline_table(BENCH)
    assert "| partial | 11.0 | 9.5 (1 failed) | 1.2x |" in out
    assert "| all-failed | 21.0 | failed | - |" in out
    assert "| **1 of 2 completed on both** | **11** | **10** | **1.2x** |" in out
    assert "runs that did not complete: Reference 0, Pixeltable 4" in out


def test_chart_renders_a_fixture_that_never_completed():
    parts, _ = render_results.pipeline_chart(BENCH, 0)
    assert any("failed (Pixeltable)" in p for p in parts)
