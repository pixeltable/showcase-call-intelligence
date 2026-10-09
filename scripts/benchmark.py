#!/usr/bin/env python3
"""Time both backends on the same machine, one call in flight at a time. Writes compare/results/benchmarks.json.

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
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.client import FIXTURES, Api, backends, load_manifest, reset_llm  # noqa: E402

OUT = ROOT / "compare" / "results" / "benchmarks.json"
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


# What must match for a section measured earlier to be published beside one measured now.
SAME_SETUP = ("git_commit", "source_fingerprint", "machine", "python", "packages", "ollama")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--reads", type=int, default=50, help="Requests per read endpoint per backend")
    parser.add_argument("--fixtures", nargs="*", help="Fixture file names (default: the whole manifest)")
    parser.add_argument("--skip-pipeline", action="store_true")
    parser.add_argument("--skip-reads", action="store_true")
    args = parser.parse_args()
    if args.rounds < 1 or args.reads < 1:
        parser.error("--rounds and --reads must be positive")

    ref, pxt = backends()
    entries = [e for e in load_manifest() if not args.fixtures or e["file"] in args.fixtures]
    if not entries:
        parser.error("No fixtures matched --fixtures")
    previous = json.loads(OUT.read_text()) if OUT.is_file() else {}
    report = {"environment": environment(os.getenv("OLLAMA_HOST", "http://localhost:11434"), os.getenv("OLLAMA_MODEL", "llama3.1"))}
    if (args.skip_pipeline or args.skip_reads) and previous:
        changed = [k for k in SAME_SETUP if previous["environment"].get(k) != report["environment"].get(k)]
        if changed:
            print(f"refusing to publish sections measured in different setups ({', '.join(changed)} changed); run both", file=sys.stderr)
            return 2

    if not args.skip_pipeline:
        smallest = min(load_manifest(), key=lambda e: (FIXTURES / e["file"]).stat().st_size)
        # This warms the current process state; the script does not restart services itself.
        report["warmup_scope"] = "current service state; not a verified cold start"
        report["first_call"] = {}
        for api in (ref, pxt):
            print(f"warm-up call {api.name} ({smallest['file']})")
            report["first_call"][api.name] = time_call(api, smallest)
        pipeline: dict[str, dict[str, list]] = {e["file"]: {"reference": [], "pixeltable": []} for e in entries}
        for round_no in range(args.rounds):
            order = (ref, pxt) if round_no % 2 == 0 else (pxt, ref)
            for entry in entries:
                for api in order:
                    result = time_call(api, entry)
                    pipeline[entry["file"]][api.name].append(result)
                    print(f"  round {round_no + 1} {api.name:<10} {entry['file']:<30} {result['complete_sec']:>7}s {result['status']}")
        report["pipeline"] = pipeline
        report["pipeline_rounds"] = args.rounds
        report["pipeline_measured_at"] = report["environment"]["measured_at"]
    elif "pipeline" in previous:
        for key in ("first_call", "pipeline", "pipeline_rounds"):
            report[key] = previous[key]
        report["pipeline_measured_at"] = previous.get("pipeline_measured_at", previous["environment"]["measured_at"])

    if not args.skip_reads:
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
    elif "reads" in previous:
        report["reads"], report["reads_corpus"] = previous["reads"], previous.get("reads_corpus")
        report["reads_measured_at"] = previous.get("reads_measured_at", previous["environment"]["measured_at"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
