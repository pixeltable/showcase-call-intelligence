#!/usr/bin/env python3
"""Time both backends on the same machine, one call in flight at a time. Writes a new report under compare/reports/benchmark/.

    uv run python scripts/benchmark.py                 # 3 rounds over all 10 fixtures, then reads
    uv run python scripts/benchmark.py --rounds 1 --fixtures billing-inquiry-speech.wav

Both backends share Ollama and the CPU, so they never run together: every fixture is measured
on one backend, then the other, and the order flips each round. Before each timed call Ollama
reloads the model, so no call reuses a prompt the other backend just sent. Each backend first
ingests one untimed call, so loading WhisperX, pyannote and the embedding model in-process is
reported as a warm-up run and kept out of the medians. Model loading is included only if the services
were freshly restarted and have not processed any calls. Timed calls are deleted afterwards, which
leaves the seeded corpus the read benchmark runs against.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.client import FIXTURES, Api, backends, load_manifest, reset_llm  # noqa: E402

REPORT_DIR = ROOT / "compare" / "reports" / "benchmark"
STATE_FILE = ROOT / ".compare-state.json"
VERSION_PACKAGES = ["pixeltable", "whisperx", "torch", "sentence-transformers", "fastapi", "sqlalchemy", "celery"]


def sh(cmd: list[str], cwd: Path = ROOT) -> str:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def package_versions(backend_dir: Path) -> dict[str, str]:
    script = (
        "import importlib.metadata as m, json\n"
        f"names = {VERSION_PACKAGES!r}\n"
        "out = {}\n"
        "for n in names:\n"
        "    try: out[n] = m.version(n)\n"
        "    except m.PackageNotFoundError: pass\n"
        "print(json.dumps(out))"
    )
    raw = sh(["uv", "run", "--quiet", "python", "-c", script], backend_dir).splitlines()
    return json.loads(raw[-1]) if raw else {}


def source_fingerprint(root: Path = ROOT) -> str:
    """Fingerprint application sources, including dirty changes, without secrets or generated results."""
    paths = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "backends", "shared",
         "frontend", "scripts", "docker-compose.yml", "pyproject.toml", "uv.lock"],
        cwd=root, capture_output=True, check=True,
    ).stdout.decode().split("\0")
    digest = hashlib.sha256()
    for relative in sorted(set(paths) - {""}):
        path = root / relative
        if path.is_file():
            digest.update(relative.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def environment(ollama_host: str, model: str) -> dict:
    tags = httpx.get(f"{ollama_host}/api/tags", timeout=10).json().get("models", [])
    required = model if ":" in model else f"{model}:latest"
    digest = next((m["digest"] for m in tags if m["name"] == required), None)
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": sh(["git", "rev-parse", "--short", "HEAD"]),
        "git_dirty": bool(sh(["git", "status", "--porcelain"])),
        "source_fingerprint": source_fingerprint(),
        "machine": {
            "chip": sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor(),
            "cpus": int(sh(["sysctl", "-n", "hw.ncpu"]) or 0) or None,
            "memory_gb": round(int(sh(["sysctl", "-n", "hw.memsize"]) or 0) / 2**30) or None,
            "os": f"{platform.system()} {platform.mac_ver()[0] or platform.release()}",
        },
        "python": {"reference": sh(["uv", "run", "--quiet", "python", "-V"], ROOT / "backends" / "reference"),
                   "pixeltable": sh(["uv", "run", "--quiet", "python", "-V"], ROOT / "backends" / "pixeltable")},  # fmt: skip
        "packages": {"reference": package_versions(ROOT / "backends" / "reference"),
                     "pixeltable": package_versions(ROOT / "backends" / "pixeltable")},  # fmt: skip
        "ollama": {
            "host": ollama_host,
            "version": httpx.get(f"{ollama_host}/api/version", timeout=10).json().get("version"),
            "model": model,
            "digest": digest,
            "docker_vm": sh(["docker", "info", "--format", "{{.NCPU}} cpus, {{.MemTotal}} bytes"]),
        },
        "concurrency": "one call in flight; Reference: 1 Celery worker process; Pixeltable: 1 insert thread",
    }


def time_call(api: Api, entry: dict) -> dict:
    reset_llm()  # untimed: every call starts with the model loaded and its prompt cache empty
    started = time.perf_counter()
    call_id = api.upload(FIXTURES / entry["file"], entry, agent_suffix="bench")
    accept = time.perf_counter() - started
    waited = api.wait(call_id)
    total = time.perf_counter() - started
    result = {
        "accept_sec": round(accept, 3),
        "complete_sec": round(total, 2),
        "status": waited.call["status"],
        "error": waited.call.get("error_message"),
        "segments": len(waited.call.get("segments") or []),
        "transitions": waited.transitions,
    }
    api.delete(call_id)
    return result


def setup_provenance(entries: list[dict], *, pipeline: bool, reads: bool) -> dict:
    """Identify the actual fixture bytes, seed state, and configured endpoints of this invocation."""
    setup = {
        "fixture_manifest_sha256": hashlib.sha256((FIXTURES / "manifest.json").read_bytes()).hexdigest(),
        "fixture_sha256": {
            entry["file"]: hashlib.sha256((FIXTURES / entry["file"]).read_bytes()).hexdigest()
            for entry in entries if pipeline
        },
        "api_urls": {"reference": os.getenv("REF_API", "http://127.0.0.1:8001"),
                     "pixeltable": os.getenv("PXT_API", "http://127.0.0.1:8000")},
        "model_config": {name: os.getenv(name) for name in (
            "WHISPERX_MODEL", "WHISPERX_DIARIZATION_MODEL", "EMBED_MODEL", "PXT_ENRICHMENT_PROFILE",
        )},
    }
    if reads:
        setup["seed_state_sha256"] = hashlib.sha256(STATE_FILE.read_bytes()).hexdigest()
    return setup


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def measure_call(api: Api, entry: dict, report: dict, *, phase: str, round_no: int | None = None) -> dict:
    attempt = {"backend": api.name, "fixture": entry["file"], "phase": phase,
               "round": round_no, "status": "running", "started_at": timestamp()}
    report["attempts"].append(attempt)
    try:
        result = time_call(api, entry)
        attempt.update(status="succeeded" if result["status"] == "completed" else "failed",
                       call_status=result["status"], error=result.get("error"))
        return result
    except Exception as exc:
        attempt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        attempt["finished_at"] = timestamp()


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def time_reads(apis: tuple[Api, Api], ids: dict[str, str], requests: dict[str, str], n: int, warmup: int = 5) -> dict:
    out: dict[str, dict] = {}
    for label, path in requests.items():
        samples: dict[str, list[float]] = {api.name: [] for api in apis}
        for i in range(warmup + n):
            order = apis if i % 2 == 0 else tuple(reversed(apis))
            for api in order:
                path_for = path.format(id=ids[api.name])
                started = time.perf_counter()
                resp = api.http.get(path_for)
                elapsed = (time.perf_counter() - started) * 1000
                if resp.status_code != 200:
                    raise RuntimeError(f"{api.name} {path_for}: HTTP {resp.status_code}")
                if i >= warmup:
                    samples[api.name].append(elapsed)
        out[label] = {
            name: {
                "n": len(v),
                "p50_ms": round(statistics.median(v), 2),
                "p95_ms": round(percentile(v, 0.95), 2),
                "mean_ms": round(statistics.fmean(v), 2),
            }
            for name, v in samples.items()
        }
        print(f"  {label:<24} " + "  ".join(f"{k} p50={v['p50_ms']}ms p95={v['p95_ms']}ms" for k, v in out[label].items()))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--reads", type=int, default=50, help="Requests per read endpoint per backend")
    parser.add_argument("--fixtures", nargs="*", help="Fixture file names (default: the whole manifest)")
    parser.add_argument("--skip-pipeline", action="store_true")
    parser.add_argument("--skip-reads", action="store_true")
    parser.add_argument("--output", type=Path, help="New JSON report path; existing files are refused before provider work")
    args = parser.parse_args(argv)
    if args.rounds < 1 or args.reads < 1:
        parser.error("--rounds and --reads must be positive")
    if args.skip_pipeline and args.skip_reads:
        parser.error("At least one measurement section must be requested")

    run_id = str(uuid.uuid4())
    output = args.output or REPORT_DIR / f"{run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = output.open("x")
    except FileExistsError:
        parser.error(f"Report already exists: {output}")
    report = {"schema_version": 2, "run_id": run_id, "started_at": timestamp(), "status": "running",
              "requested_sections": [name for name, skip in (("pipeline", args.skip_pipeline), ("reads", args.skip_reads)) if not skip],
              "sections": {}, "attempts": [],
              "configuration": {"rounds": args.rounds, "reads": args.reads, "fixtures": args.fixtures}}
    exit_code = 0
    with handle:
        try:
            manifest = load_manifest()
            entries = [e for e in manifest if not args.fixtures or e["file"] in args.fixtures]
            if not args.skip_pipeline and not entries:
                raise ValueError("No fixtures matched --fixtures")
            smallest = min(manifest, key=lambda e: (FIXTURES / e["file"]).stat().st_size) if not args.skip_pipeline else None
            report["environment"] = environment(os.getenv("OLLAMA_HOST", "http://localhost:11434"), os.getenv("OLLAMA_MODEL", "llama3.1"))
            report["setup"] = setup_provenance(entries + ([smallest] if smallest else []),
                                                pipeline=not args.skip_pipeline, reads=not args.skip_reads)
            report["setup"]["identity"] = hashlib.sha256(json.dumps(
                {"environment": report["environment"], "setup": report["setup"]}, sort_keys=True,
            ).encode()).hexdigest()
            ref, pxt = backends()

            if not args.skip_pipeline:
                section = {"status": "running", "started_at": timestamp()}
                report["sections"]["pipeline"] = section
                # This warms the current process state; the script does not restart services itself.
                report["warmup_scope"] = "current service state; not a verified cold start"
                report["first_call"] = {}
                for api in (ref, pxt):
                    print(f"warm-up call {api.name} ({smallest['file']})")
                    report["first_call"][api.name] = measure_call(api, smallest, report, phase="warmup")
                pipeline = {e["file"]: {"reference": [], "pixeltable": []} for e in entries}
                report["pipeline"] = pipeline
                report["pipeline_rounds"] = args.rounds
                report["pipeline_measured_at"] = report["environment"]["measured_at"]
                for round_no in range(args.rounds):
                    order = (ref, pxt) if round_no % 2 == 0 else (pxt, ref)
                    for entry in entries:
                        for api in order:
                            result = measure_call(api, entry, report, phase="timed", round_no=round_no + 1)
                            pipeline[entry["file"]][api.name].append(result)
                            print(f"  round {round_no + 1} {api.name:<10} {entry['file']:<30} {result['complete_sec']:>7}s {result['status']}")
                section.update(status="failed" if any(a["status"] == "failed" for a in report["attempts"]) else "succeeded",
                               finished_at=timestamp())

            if not args.skip_reads:
                section = {"status": "running", "started_at": timestamp()}
                report["sections"]["reads"] = section
                state = json.loads(STATE_FILE.read_text())
                first = next(iter(state.values()))
                print(f"reads ({args.reads} per endpoint per backend, interleaved)")
                report["reads"] = time_reads(
                    (ref, pxt),
                    {"reference": first["ref_id"], "pixeltable": first["pxt_id"]},
                    {
                        "list calls": "/api/calls?limit=50",
                        "call detail": "/api/calls/{id}",
                        "kpis": "/api/calls/kpis",
                        "flagged": "/api/calls/flagged",
                        "search keyword": "/api/search?q=billing&mode=keyword",
                        "search semantic": "/api/search?q=monthly%20subscription%20fees&mode=semantic",
                        "search hybrid": "/api/search?q=refund&mode=hybrid",
                    },
                    args.reads,
                )
                report["reads_corpus"] = {"calls": len(state)}
                report["reads_measured_at"] = report["environment"]["measured_at"]
                section.update(status="succeeded", finished_at=timestamp())
            report["status"] = "failed" if any(s["status"] == "failed" for s in report["sections"].values()) else "succeeded"
            exit_code = int(report["status"] == "failed")
        except KeyboardInterrupt:
            report.update(status="interrupted", error="KeyboardInterrupt")
            exit_code = 130
        except Exception as exc:
            report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            exit_code = 1
        finally:
            for entry in [*report["sections"].values(), *report["attempts"]]:
                if entry["status"] == "running":
                    entry.update(status=report["status"], error=report.get("error"), finished_at=timestamp())
            report["finished_at"] = timestamp()
            handle.write(json.dumps(report, indent=2) + "\n")
    print(f"wrote {output}. Historical published results are unchanged.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
