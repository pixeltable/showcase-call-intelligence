#!/usr/bin/env python3
"""Change a running, seeded system on both backends and measure what each change costs.

    uv run python scripts/bench_evolve.py                    # both experiments
    uv run python scripts/bench_evolve.py --full-reprocess   # also re-run the whole Reference pipeline

1. Add a field to live data: a sixth LLM enrichment, `topics`, for calls already processed.
2. Re-run one step: the summary prompt changes; recompute summaries, leave transcripts alone.
3. Recover from an LLM outage: Ollama stops while a call is processed, then comes back.

Each change is a patch in compare/evolve/, applied, timed, verified over HTTP, and reverted, so
the repo's line counts keep measuring the product. Writes compare/results/evolve.json.
Run through the environment ./scripts/run_compare.sh exports; re-seed afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.client import FIXTURES, backends, load_manifest, reset_llm  # noqa: E402
from metrics import code_lines_in  # noqa: E402

EVOLVE = ROOT / "compare" / "evolve"
OUT = ROOT / "compare" / "results" / "evolve.json"
PIDS = ROOT / ".compare-pids"
REF_DIR, PXT_DIR = ROOT / "backends" / "reference", ROOT / "backends" / "pixeltable"
STATE_FILE = ROOT / ".compare-state.json"


def state() -> dict:
    return json.loads(STATE_FILE.read_text())


# ---------------------------------------------------------------- measuring a patch


def patch_cost(*names: str) -> dict:
    """Files touched and code lines added/removed, counted like scripts/metrics.py counts code."""
    files: dict[str, dict[str, int]] = {}
    current = None
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for name in names:
        for line in (EVOLVE / name).read_text().splitlines():
            if line.startswith("+++ "):
                current = line[6:]
            elif line.startswith("--- ") or current is None:
                continue
            elif line.startswith("+"):
                added.setdefault(current, []).append(line[1:])
            elif line.startswith("-"):
                removed.setdefault(current, []).append(line[1:])
    for path in sorted(set(added) | set(removed)):
        suffix = Path(path).suffix
        files[path] = {
            "added": len(code_lines_in("\n".join(added.get(path, [])), suffix)),
            "removed": len(code_lines_in("\n".join(removed.get(path, [])), suffix)),
        }
    return {
        "files_touched": len(files),
        "lines_added": sum(f["added"] for f in files.values()),
        "lines_removed": sum(f["removed"] for f in files.values()),
        "files": files,
    }


def git_apply(*names: str, reverse: bool = False) -> None:
    cmd = ["git", "apply", *(["-R"] if reverse else []), *(str(EVOLVE / n) for n in names)]
    subprocess.run(cmd, cwd=ROOT, check=True)


# ------------------------------------------------------------------ running steps


class Steps:
    """The operator steps one backend needs, each timed."""

    def __init__(self) -> None:
        self.steps: list[dict] = []

    def run(self, label: str, cmd: list[str], cwd: Path, *, listing: bool = False) -> str:
        """Run one step; a `listing` step reports through its output, not its exit code."""
        started = time.perf_counter()
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        elapsed = round(time.perf_counter() - started, 2)
        self.steps.append({"step": label, "command": " ".join(cmd), "sec": elapsed, "ok": out.returncode == 0 or listing})
        print(f"    {elapsed:>7.2f}s  {label}")
        if out.returncode != 0 and not listing:
            raise RuntimeError(f"{label} failed:\n{out.stdout[-1500:]}\n{out.stderr[-1500:]}")
        return out.stdout

    def call(self, label: str, fn) -> object:
        started = time.perf_counter()
        result = fn()
        elapsed = round(time.perf_counter() - started, 2)
        self.steps.append({"step": label, "sec": elapsed, "ok": True})
        print(f"    {elapsed:>7.2f}s  {label}")
        return result

    def total(self) -> float:
        return round(sum(s["sec"] for s in self.steps), 2)


def pxt(*args: str) -> list[str]:
    return ["uv", "run", "--quiet", "pxt", *args]


def restart_reference() -> None:
    """Stop and start the API and the Celery worker the way run_compare.sh starts them."""
    for name in ("ref-api", "ref-celery"):
        pid_file = PIDS / f"{name}.pid"
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass
    time.sleep(3)
    port = os.environ.get("REF_API_PORT", "8001")
    commands = {
        "ref-api": ["uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port],
        "ref-celery": ["uv", "run", "celery", "-A", "worker.celery_app", "worker", "-l", "info", "-n", "ref@%h", "-c", "1"],
    }
    for name, cmd in commands.items():
        log = (PIDS / f"{name}.log").open("a")
        proc = subprocess.Popen(cmd, cwd=REF_DIR, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (PIDS / f"{name}.pid").write_text(f"{proc.pid}\n")
    ref, _ = backends()
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if ref.health()["checks"]["celery"]["ok"]:
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Reference did not come back healthy")


def seeded_ids(backend: str) -> list[str]:
    key = "ref_id" if backend == "reference" else "pxt_id"
    return [ids[key] for ids in state().values()]


def upload_one(api) -> dict:
    entry = next(e for e in load_manifest() if e["file"] == "billing-inquiry-speech.wav")
    call = api.wait(api.upload(FIXTURES / entry["file"], entry, agent_suffix="evolve")).call
    api.delete(call["id"])
    return call


# ------------------------------------------------------ 1. add a field to live data


def add_field() -> dict:
    print("\n1. Add a field to live data: `topics` for every processed call")
    ref, pxt_api = backends()
    result = {"shared": patch_cost("topics-shared.patch")}
    git_apply("topics-shared.patch", "topics-pixeltable.patch", "topics-reference.patch")
    try:
        for api, patch in ((pxt_api, "topics-pixeltable.patch"), (ref, "topics-reference.patch")):
            print(f"  {api.name}")
            reset_llm()  # untimed: same model state and an empty prompt cache for each backend
            steps = Steps()
            if api.name == "pixeltable":
                # shared/ sits outside the Pixeltable project root; the daemon keeps it cached until restarted
                steps.run("restart the pxt daemon (shared module changed)", pxt("daemon", "restart"), PXT_DIR)
                steps.run("pxt schema update: add the column, backfill every row", pxt("schema", "update", "app.py", "call_center", "-f"), PXT_DIR)
                steps.run("pxt service update: serve the new column", pxt("service", "update", "app.py", "call_center", "-f"), PXT_DIR)
            else:
                steps.run("alembic upgrade head: add the column", ["uv", "run", "alembic", "upgrade", "head"], REF_DIR)
                steps.call("restart the API and the Celery worker", restart_reference)
                steps.run(
                    "run the backfill task over every processed call",
                    ["uv", "run", "python", "-c", "from worker.tasks.backfill_topics import backfill_topics; print(backfill_topics())"],
                    REF_DIR,
                )
            calls = [api.detail(i) for i in seeded_ids(api.name)]
            new_call = upload_one(api)
            result[api.name] = {
                "cost": patch_cost(patch),
                "steps": steps.steps,
                "total_sec": steps.total(),
                "rows": len(calls),
                "rows_with_topics_field": sum(isinstance(c.get("topics"), list) for c in calls),
                "rows_with_topics": sum(bool(c.get("topics")) for c in calls),
                "new_call_has_topics": bool(new_call.get("topics")),
                "example": calls[0].get("topics"),
            }
            print(f"    topics on {result[api.name]['rows_with_topics']}/{len(calls)} rows; new call: {result[api.name]['new_call_has_topics']}")
    finally:
        revert_add_field()
    return result


def revert_add_field() -> None:
    print("  reverting")
    subprocess.run(["uv", "run", "alembic", "downgrade", "003_vertical"], cwd=REF_DIR, check=False)
    git_apply("topics-shared.patch", "topics-pixeltable.patch", "topics-reference.patch", reverse=True)
    subprocess.run(pxt("daemon", "restart"), cwd=PXT_DIR, check=False)
    subprocess.run(pxt("schema", "update", "app.py", "call_center", "--allow-destructive", "-f"), cwd=PXT_DIR, check=False)
    subprocess.run(pxt("service", "update", "app.py", "call_center", "--allow-destructive", "-f"), cwd=PXT_DIR, check=False)
    restart_reference()


# ------------------------------------------------------------- 2. re-run one step


def snapshot(api) -> dict:
    out = {}
    for call_id in seeded_ids(api.name):
        c = api.detail(call_id)
        out[call_id] = {"summary": c["summary"], "segments": [(s["id"], s["text"]) for s in c["segments"]], "comments": c["comments"]}
    return out


def anchor_comment(api) -> str:
    call_id = seeded_ids(api.name)[0]
    seg = api.detail(call_id)["segments"][0]
    api.comment(call_id, segment_id=seg["id"], start_sec=seg["start_sec"], author="evolve", text="anchor probe")
    return call_id


def effects(api, before: dict, probe_call: str) -> dict:
    after = snapshot(api)
    changed = sum(after[i]["summary"] != before[i]["summary"] for i in after)
    same_segments = sum(after[i]["segments"] == before[i]["segments"] for i in after)
    anchors = [c["segment_id"] for c in after[probe_call]["comments"] if c["comment"] == "anchor probe"]
    return {
        "rows": len(after),
        "summaries_changed": changed,
        "transcripts_untouched": same_segments,
        "probe_comment_still_anchored": bool(anchors) and all(a is not None for a in anchors),
    }


def rerun_step(full_reprocess: bool) -> dict:
    print("\n2. Re-run one step: new summary prompt, recompute summaries")
    ref, pxt_api = backends()
    result = {"shared": patch_cost("summary-prompt-shared.patch")}
    probes = {api.name: anchor_comment(api) for api in (ref, pxt_api)}
    git_apply("summary-prompt-shared.patch")
    try:
        print("  pixeltable")
        before = snapshot(pxt_api)
        reset_llm()
        steps = Steps()
        steps.run("restart the pxt daemon (shared module changed)", pxt("daemon", "restart"), PXT_DIR)
        steps.run("pxt recompute calls summary: one LLM call per row", pxt("recompute", "call_center/calls", "summary", "-f"), PXT_DIR)
        steps.run("pxt service restart: new uploads use the new prompt", pxt("service", "restart", "call_center/api"), PXT_DIR)
        result["pixeltable"] = {"cost": {"files_touched": 0, "lines_added": 0, "lines_removed": 0, "files": {}},
                                "steps": steps.steps, "total_sec": steps.total(), **effects(pxt_api, before, probes["pixeltable"])}  # fmt: skip

        print("  reference: a task written for this")
        git_apply("summary-rerun-reference.patch")
        try:
            before = snapshot(ref)
            reset_llm()
            steps = Steps()
            steps.call("restart the API and the Celery worker", restart_reference)
            steps.run(
                "run the re-summarize task over every processed call",
                ["uv", "run", "python", "-c", "from worker.tasks.resummarize import resummarize; print(resummarize())"],
                REF_DIR,
            )
            result["reference"] = {"cost": patch_cost("summary-rerun-reference.patch"), "steps": steps.steps,
                                   "total_sec": steps.total(), **effects(ref, before, probes["reference"])}  # fmt: skip
        finally:
            git_apply("summary-rerun-reference.patch", reverse=True)

        if full_reprocess:
            print("  reference: the path it already has, re-queueing process_call")
            before = snapshot(ref)
            reset_llm()
            steps = Steps()
            steps.call("restart the API and the Celery worker", restart_reference)

            def requeue_and_wait() -> None:
                ids = seeded_ids("reference")
                script = "import sys\nfrom worker.tasks.process_call import process_call\nfor i in sys.argv[1:]: process_call.delay(i)"
                subprocess.run(["uv", "run", "python", "-c", script, *ids], cwd=REF_DIR, check=True)
                # A queued call still shows its old `completed` until the worker reaches it; a re-run is
                # done when its segments have been re-created, which gives them new ids.
                deadline = time.time() + 3600
                for call_id in ids:
                    old = {sid for sid, _ in before[call_id]["segments"]}
                    while time.time() < deadline:
                        call = ref.detail(call_id)
                        if call["status"] in ("completed", "failed") and old.isdisjoint(s["id"] for s in call["segments"]):
                            break
                        time.sleep(1)

            steps.call("re-queue process_call for every call and wait", requeue_and_wait)
            result["reference_full_reprocess"] = {"cost": {"files_touched": 0, "lines_added": 0, "lines_removed": 0, "files": {}},
                                                  "steps": steps.steps, "total_sec": steps.total(),
                                                  **effects(ref, before, probes["reference"])}  # fmt: skip
    finally:
        git_apply("summary-prompt-shared.patch", reverse=True)
        subprocess.run(pxt("daemon", "restart"), cwd=PXT_DIR, check=False)
        subprocess.run(pxt("service", "restart", "call_center/api"), cwd=PXT_DIR, check=False)
        restart_reference()
    return result


# ---------------------------------------------------- 3. recover from an LLM outage

OLLAMA_CONTAINER = "call-center-transcription-ollama-1"
ENRICHMENTS = ("summary", "action_items", "sentiment", "category", "qa_scorecard")


def ollama_up(timeout_sec: float = 300) -> None:
    subprocess.run(["docker", "start", OLLAMA_CONTAINER], check=True, capture_output=True)
    host, model = os.getenv("OLLAMA_HOST", "http://localhost:11434"), os.getenv("OLLAMA_MODEL", "llama3.1")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            import httpx

            httpx.post(f"{host}/api/generate", json={"model": model, "prompt": "", "stream": False}, timeout=300)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Ollama did not come back")


def recover_failed_step() -> dict:
    print("\n3. Recover from an LLM outage: Ollama is down while a call is processed")
    ref, pxt_api = backends()
    entry = next(e for e in load_manifest() if e["file"] == "billing-inquiry-speech.wav")
    subprocess.run(["docker", "stop", OLLAMA_CONTAINER], check=True, capture_output=True)
    try:
        ids = {api.name: api.upload(FIXTURES / entry["file"], entry, agent_suffix="outage") for api in (ref, pxt_api)}
        failed = {api.name: api.wait(ids[api.name]).call for api in (ref, pxt_api)}
    finally:
        ollama_up()
    result: dict = {}
    try:
        for api in (pxt_api, ref):
            call_id, before = ids[api.name], failed[api.name]
            print(f"  {api.name}: status {before['status']} with {len(before['segments'])} segments kept")
            reset_llm()
            steps = Steps()
            failed_columns: set[str] = set()
            if api.name == "pixeltable":
                out = steps.run("pxt errors: which cells failed", pxt("errors", "call_center/calls", "--json"), PXT_DIR, listing=True)
                entries = json.loads(out or "[]")
                failed_columns = {e["column"] for e in entries if str(e["pk"].get("id")) == call_id}
                for col in ENRICHMENTS:
                    if any(e["column"] == col for e in entries):
                        steps.run(f"pxt recompute {col} --errors-only", pxt("recompute", "call_center/calls", col, "--errors-only", "-f"), PXT_DIR)
            else:
                script = f"from worker.tasks.resume_call import resume_call_processing; resume_call_processing({call_id!r})"
                steps.run("run the resume task written for this (resume_call.py)", ["uv", "run", "python", "-c", script], REF_DIR)
            after = api.detail(call_id)
            result[api.name] = {
                "status_after_outage": before["status"],
                "segments_kept_through_outage": len(before["segments"]),
                "error_after_outage": (before.get("error_message") or "")[:200],
                "failed_cells": sorted(failed_columns) if api.name == "pixeltable" else None,
                "steps": steps.steps,
                "total_sec": steps.total(),
                "status_after_recovery": after["status"],
                "transcript_untouched": [s["text"] for s in after["segments"]] == [s["text"] for s in before["segments"]],
                "searchable_after_recovery": any(h["call_id"] == call_id for h in api.search("billing", limit=100)),
            }
            print(f"    -> {after['status']}")
    finally:
        for api in (ref, pxt_api):
            api.delete(ids[api.name])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full-reprocess", action="store_true", help="Also time the Reference's only existing path")
    parser.add_argument("--only", choices=["add_field", "rerun_step", "recover"])
    args = parser.parse_args()
    if subprocess.run(["git", "diff", "--quiet", "--", "shared", "backends"], cwd=ROOT).returncode != 0:
        print("note: the tree has uncommitted changes; patches apply on top of them")
    report = json.loads(OUT.read_text()) if OUT.is_file() else {}
    report["measured_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["model"] = os.getenv("OLLAMA_MODEL", "llama3.1")
    report["rows"] = len(state())
    experiments = {
        "add_field": add_field,
        "rerun_step": lambda: rerun_step(args.full_reprocess),
        "recover": recover_failed_step,
    }
    failed = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for key, run in experiments.items():
        if args.only not in (None, key):
            continue
        try:
            report[key] = run()
        except Exception as exc:  # recorded, and the next experiment still runs
            failed.append(key)
            print(f"\n{key} did not finish: {exc}")
        finally:
            OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nwrote {OUT.relative_to(ROOT)}. Re-seed before the next benchmark: ./scripts/run_compare.sh seed")
    if failed:
        print(f"re-run with --only {' / --only '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
