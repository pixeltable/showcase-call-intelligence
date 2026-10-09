#!/usr/bin/env python3
"""Render compare/results/*.svg and the generated tables in the docs from the committed JSON.

    uv run python scripts/render_results.py            # write
    uv run python scripts/render_results.py --check    # exit 1 if any output would change (CI)

Pure-stdlib SVG, so the render is deterministic and the check is a byte comparison. Every number
comes from compare/results/metrics.json, benchmarks.json or evolve.json; none is typed here.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "compare" / "results"
DOCS = [ROOT / "README.md", ROOT / "compare" / "WHY_PIXELTABLE.md", ROOT / "compare" / "METHODOLOGY.md"]

BACKENDS = ("reference", "pixeltable")
LABEL = {"reference": "Reference (Celery + Postgres)", "pixeltable": "Pixeltable"}
SHORT = {"reference": "Reference", "pixeltable": "Pixeltable"}
W = 920

STYLE = """<style>
  .surface { fill: #fcfcfb; } .ink { fill: #0b0b0b; } .ink2 { fill: #52514e; } .muted { fill: #898781; }
  .grid { stroke: #e1e0d9; } .axis { stroke: #c3c2b7; }
  .reference { fill: #eb6834; } .pixeltable { fill: #2a78d6; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; } .ink { fill: #ffffff; } .ink2 { fill: #c3c2b7; }
    .grid { stroke: #2c2c2a; } .axis { stroke: #383835; }
    .reference { fill: #d95926; } .pixeltable { fill: #3987e5; }
  }
  text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
</style>"""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x: float, y: float, s: str, *, size: int = 11, cls: str = "ink", anchor: str = "start", bold: bool = False) -> str:
    weight = ' font-weight="600"' if bold else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" class="{cls}" text-anchor="{anchor}"{weight}>{esc(s)}</text>'


def bar(x: float, y: float, w: float, h: float, cls: str, title: str) -> str:
    """Rounded data end, square at the baseline: a rect clipped by a rounded twin."""
    w = max(w, 1.0)
    r = min(4.0, w / 2, h / 2)
    path = (
        f"M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z"
    )
    return f'<path d="{path}" class="{cls}"><title>{esc(title)}</title></path>'


def legend(x: float, y: float) -> list[str]:
    out, cx = [], x
    for b in BACKENDS:
        out.append(f'<rect x="{cx:.1f}" y="{y - 9:.1f}" width="10" height="10" rx="2" class="{b}"/>')
        out.append(text(cx + 14, y, LABEL[b], size=11, cls="ink2"))
        cx += 14 + 7 * len(LABEL[b]) + 18
    return out


def nice_ticks(hi: float, n: int = 5) -> list[float]:
    raw = hi / n
    mag = 10 ** len(str(int(raw))) / 10 if raw >= 1 else 1
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    return [step * i for i in range(int(hi / step) + 2)]


def fmt(v: float, unit: str) -> str:
    if v == 0:
        return "0" if unit == "n" else f"0{unit}"
    if unit == "s":
        return f"{v:.0f}s" if v >= 10 else f"{v:.1f}s"
    if unit == "ms":
        return f"{v:.0f}ms" if v >= 10 else f"{v:.1f}ms"
    return f"{v:,.0f}"


def grouped_bars(title: str, subtitle: str, rows: list[tuple[str, dict[str, float | None]]], unit: str, top: float,
                 missing: str = "n/a") -> tuple[list[str], float]:
    """One group per row, one bar per backend, a shared linear axis from zero. `missing` labels a value of None."""
    left, right = 230.0, W - 70.0
    bar_h, gap, group_gap = 11.0, 2.0, 12.0
    group_h = 2 * bar_h + gap + group_gap
    y0 = top + 46
    hi = max(v for _, vals in rows for v in vals.values() if v is not None) or 1
    ticks = nice_ticks(hi)
    hi = ticks[-1]

    def x(v: float) -> float:
        return left + v / hi * (right - left)

    parts = [text(30, top + 16, title, size=15, bold=True), text(30, top + 33, subtitle, size=11, cls="ink2")]
    parts += legend(right - 380, top + 16)
    bottom = y0 + len(rows) * group_h - group_gap
    for t in ticks:
        parts.append(f'<line x1="{x(t):.1f}" y1="{y0 - 6:.1f}" x2="{x(t):.1f}" y2="{bottom:.1f}" class="grid" stroke-width="1"/>')
        parts.append(text(x(t), bottom + 15, fmt(t, unit), size=10, cls="muted", anchor="middle"))
    parts.append(f'<line x1="{left:.1f}" y1="{y0 - 6:.1f}" x2="{left:.1f}" y2="{bottom:.1f}" class="axis" stroke-width="1"/>')
    for i, (label, vals) in enumerate(rows):
        gy = y0 + i * group_h
        parts.append(text(left - 10, gy + bar_h + 4, label, size=11, anchor="end"))
        for j, b in enumerate(BACKENDS):
            by = gy + j * (bar_h + gap)
            if vals.get(b) is None:
                parts.append(text(left + 5, by + bar_h - 2, f"{missing} ({SHORT[b]})", size=10, cls="muted"))
                continue
            parts.append(bar(left, by, x(vals[b]) - left, bar_h, b, f"{label}, {SHORT[b]}: {fmt(vals[b], unit)}"))
            parts.append(text(x(vals[b]) + 5, by + bar_h - 2, fmt(vals[b], unit), size=10, cls="ink2"))
    return parts, bottom + 30


def svg(parts: list[str], height: float) -> str:
    body = "".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height:.0f}" role="img">{STYLE}'
        f'<rect width="{W}" height="{height:.0f}" class="surface"/>{body}</svg>\n'
    )


# ---------------------------------------------------------------------- data views


def median(values: list[float]) -> float:
    return round(statistics.median(values), 2)


def pipeline_medians(bench: dict) -> dict[str, dict[str, float | None]]:
    """Median seconds of the completed runs; None when no run of that backend completed."""
    out: dict[str, dict[str, float | None]] = {}
    for fixture, per_backend in bench["pipeline"].items():
        done = {b: [r["complete_sec"] for r in per_backend[b] if r["status"] == "completed"] for b in BACKENDS}
        out[fixture] = {b: median(done[b]) if done[b] else None for b in BACKENDS}
    return out


def pipeline_failures(bench: dict) -> dict[str, dict[str, int]]:
    return {f: {b: sum(r["status"] != "completed" for r in runs[b]) for b in BACKENDS} for f, runs in bench["pipeline"].items()}


def by_reference_median(item: tuple[str, dict]) -> float:
    return item[1]["reference"] if item[1]["reference"] is not None else float("inf")


def concern_totals(m: dict) -> dict[str, dict[str, int]]:
    """Lines per top-level concern, per backend (the grouping is hand-classified in metrics.py)."""
    out: dict[str, dict[str, int]] = {}
    for b in BACKENDS:
        for name, loc in m[b]["by_concern"].items():
            head = name.partition(" / ")[0]
            out.setdefault(head, {}).setdefault(b, 0)
            out[head][b] += loc
    return dict(sorted(out.items(), key=lambda kv: -max(kv[1].values())))


def code_chart(metrics: dict) -> tuple[list[str], float]:
    m = metrics["backends"]
    rows = [("All app code", {b: m[b]["app_loc"] for b in BACKENDS})]
    rows += [(head, {b: vals.get(b) for b in BACKENDS}) for head, vals in concern_totals(m).items()]
    return grouped_bars(
        "Where each backend's lines go",
        f"Non-blank, non-comment lines; concerns grouped by hand. Both import {metrics['shared']['app_loc']} shared lines, counted in neither.",
        rows,
        "n",
        0,
    )


def evolve_chart(evolve: dict, top: float) -> tuple[list[str], float]:
    a, r = evolve["add_field"], evolve["rerun_step"]
    rows = [
        ("Add a field to live data", {b: a[b]["cost"]["lines_added"] for b in BACKENDS}),
        ("Re-run one step", {b: r[b]["cost"]["lines_added"] for b in BACKENDS}),
    ]
    return grouped_bars(
        "Lines written to change the running system",
        f"Backend code only. The shared part of the new field ({a['shared']['cost_label']}) is the same for both.",
        rows,
        "n",
        top,
    )


def pipeline_chart(bench: dict, top: float) -> tuple[list[str], float]:
    med = pipeline_medians(bench)
    rows = sorted(med.items(), key=by_reference_median)
    return grouped_bars(
        "Upload to completed, per fixture",
        f"Median of {bench['pipeline_rounds']} runs, one call in flight, Ollama reloaded before each. LLM: {bench['environment']['ollama']['model']}.",
        [(Path(k).stem, v) for k, v in rows],
        "s",
        top,
        missing="failed",
    )


def reads_chart(bench: dict, top: float) -> tuple[list[str], float]:
    rows = [(label, {b: v[b]["p50_ms"] for b in BACKENDS}) for label, v in bench["reads"].items()]
    corpus = bench.get("reads_corpus", {}).get("calls")
    return grouped_bars(
        "Read latency, p50",
        f"{bench['reads'][next(iter(bench['reads']))]['reference']['n']} interleaved requests per endpoint over {corpus} calls.",
        rows,
        "ms",
        top,
    )


# ------------------------------------------------------------------ doc tables


def table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def cell(v) -> str:
    return "n/a" if v is None else (f"{v:,}" if isinstance(v, int) else str(v))


def ratio(a: float, b: float) -> str:
    return f"{a / b:.1f}x" if b else "n/a"


def tables(metrics: dict, bench: dict | None, evolve: dict | None) -> dict[str, str]:
    m = metrics["backends"]
    rows = [
        ("App code you maintain (lines)", "app_loc"),
        ("Files", "app_files"),
        ("Project config files: pyproject.toml, alembic.ini (lines)", "config_loc"),
        ("Tables", "tables"),
        ("Views", "views"),
        ("Vector indexes", "vector_indexes"),
        ("Migration files", "migrations"),
        ("Task-queue tasks", "task_queue_tasks"),
        ("Status writes in pipeline code", "status_writes"),
        ("Routes with a hand-written handler", "routes_hand_written"),
        ("Routes declared from a query", "routes_declared"),
        ("Orchestration hops", "orchestration_hops"),
    ]
    out = {
        "code": table(
            ["Measured from source", "Reference", "Pixeltable"],
            [[label, cell(m["reference"][k]), cell(m["pixeltable"][k])] for label, k in rows]
            + [["Processes to run (hand-classified)", str(len(m["reference"]["classified"]["processes_to_run"])),
                str(len(m["pixeltable"]["classified"]["processes_to_run"]))]],  # fmt: skip
        )
    }
    out["concerns"] = concerns_table(m)
    out["pipeline_code"] = "```python\n" + pipeline_excerpt() + "\n```"
    if bench and "pipeline" in bench:
        out["pipeline"] = pipeline_table(bench)
        out["stages"] = stage_table(bench)
    if bench and "reads" in bench:
        out["reads"] = table(
            ["Endpoint", "Reference p50", "Pixeltable p50", "Reference p95", "Pixeltable p95"],
            [[label, f"{v['reference']['p50_ms']}ms", f"{v['pixeltable']['p50_ms']}ms", f"{v['reference']['p95_ms']}ms",
              f"{v['pixeltable']['p95_ms']}ms"] for label, v in bench["reads"].items()],  # fmt: skip
        )
    if bench:
        env = bench["environment"]
        pk = env["packages"]
        out["environment"] = (
            f"{env['machine']['chip']}, {env['machine']['cpus']} cores, {env['machine']['memory_gb']} GB, {env['machine']['os']}; "
            f"{env['python']['pixeltable']}; Pixeltable {pk['pixeltable'].get('pixeltable')}, WhisperX {pk['pixeltable'].get('whisperx')}, "
            f"torch {pk['pixeltable'].get('torch')}; Ollama {env['ollama']['version']} serving `{env['ollama']['model']}` "
            f"({(env['ollama']['digest'] or '')[:12]}) in Docker ({env['ollama']['docker_vm']}). {measured_when(bench)} at "
            f"`{env['git_commit']}`{' with local changes' if env['git_dirty'] else ''}."
        )
    if evolve:
        out["evolve"] = evolve_table(evolve, m)
    return out


def measured_when(bench: dict) -> str:
    """One time when pipeline and reads were measured together, both when they were not."""
    pipeline, reads = bench.get("pipeline_measured_at"), bench.get("reads_measured_at")
    if pipeline and reads and pipeline != reads:
        return f"Pipeline measured {pipeline}, reads {reads},"
    return f"Measured {pipeline or reads or bench['environment']['measured_at']}"


def pipeline_table(bench: dict) -> str:
    """Median seconds per fixture. A cell names its failed runs; a fixture a backend never completed says so and
    leaves the totals, which sum only the fixtures both backends completed."""
    med, fails = pipeline_medians(bench), pipeline_failures(bench)

    def cell(fixture: str, b: str) -> str:
        v, n = med[fixture][b], fails[fixture][b]
        if v is None:
            return "failed"
        return f"{v:.1f}" + (f" ({n} failed)" if n else "")

    body = [
        [Path(k).stem, cell(k, "reference"), cell(k, "pixeltable"),
         ratio(v["reference"], v["pixeltable"]) if None not in v.values() else "-"]
        for k, v in sorted(med.items(), key=by_reference_median)
    ]  # fmt: skip
    both = [v for v in med.values() if None not in v.values()]
    tot = {b: sum(v[b] for v in both) for b in BACKENDS}
    label = f"All {len(med)}" if len(both) == len(med) else f"{len(both)} of {len(med)} completed on both"
    body.append([f"**{label}**", f"**{tot['reference']:.0f}**", f"**{tot['pixeltable']:.0f}**", f"**{ratio(tot['reference'], tot['pixeltable'])}**"])
    out = table(["Fixture (median seconds)", "Reference", "Pixeltable", "Ref / Pxt"], body)
    failed = {b: sum(f[b] for f in fails.values()) for b in BACKENDS}
    runs = sum(len(f["reference"]) for f in bench["pipeline"].values())
    out += (
        f"\n\n{runs} timed runs per backend; runs that did not complete: Reference {failed['reference']},"
        f" Pixeltable {failed['pixeltable']} (medians use completed runs; errors are in `benchmarks.json`)."
    )
    cold = bench.get("first_call", {})
    if cold:
        accept = {b: median([r["accept_sec"] for f in bench["pipeline"].values() for r in f[b]]) for b in BACKENDS}
        out += (
            f"\n\nWarm-up call (process coldness not verified): Reference {cold['reference']['complete_sec']:.1f}s,"
            f" Pixeltable {cold['pixeltable']['complete_sec']:.1f}s. Upload accepted in"
            f" {accept['reference'] * 1000:.0f}ms and {accept['pixeltable'] * 1000:.0f}ms (median)."
        )
    return out


STAGE_OF = {"queued": "Queued", "transcribing": "Transcribe and diarize (WhisperX)", "diarizing": "Transcribe and diarize (WhisperX)",
            "enriching": "Five LLM enrichments", "embedding": "Embed segments"}  # fmt: skip


def stage_table(bench: dict) -> str:
    """Where a Reference call's time goes, from the statuses it committed (Pixeltable reports none)."""
    per_run: list[dict[str, float]] = []
    for runs in bench["pipeline"].values():
        for run in runs["reference"]:
            if run["status"] != "completed":
                continue
            spent: dict[str, float] = {}
            marks = run["transitions"]
            for (t0, status), (t1, _) in zip(marks, marks[1:], strict=False):
                stage = STAGE_OF.get(status)
                if stage:
                    spent[stage] = spent.get(stage, 0.0) + (t1 - t0)
            per_run.append(spent)
    stages = list(dict.fromkeys(STAGE_OF.values()))
    med = {st: median([r.get(st, 0.0) for r in per_run]) for st in stages}
    total = sum(med.values()) or 1
    # A stage shorter than the 0.5 s poll interval is often never observed; say so rather than print 0.
    rows = [[st, f"{med[st]:.1f}" if med[st] >= 0.5 else "< 0.5", f"{med[st] / total:.0%}" if med[st] >= 0.5 else "-"]
            for st in stages]  # fmt: skip
    return table([f"Reference stage, median of {len(per_run)} runs", "Seconds", "Share"], rows)


def concerns_table(m: dict) -> str:
    """Top-level concerns on both sides; the Reference's schema-and-pipeline lines split beneath."""
    top: dict[str, dict[str, int]] = {}
    subs: dict[str, dict[str, int]] = {}
    for b in BACKENDS:
        for name, loc in m[b]["by_concern"].items():
            head, _, sub = name.partition(" / ")
            top.setdefault(head, {}).setdefault(b, 0)
            top[head][b] += loc
            if sub:
                subs.setdefault(head, {})[sub] = loc
    rows = []
    for head, vals in sorted(top.items(), key=lambda kv: -max(kv[1].values())):
        rows.append([head] + [cell(vals.get(b)) for b in BACKENDS])
        for sub, loc in sorted(subs.get(head, {}).items(), key=lambda kv: -kv[1]):
            rows.append([f"&nbsp;&nbsp;of which {sub}", cell(loc), ""])
    rows.append(["**Total**"] + [f"**{m[b]['app_loc']:,}**" for b in BACKENDS])
    return table(["Concern (hand-classified; lines measured)", "Reference", "Pixeltable"], rows)


def pipeline_excerpt() -> str:
    """The Calls and TranscriptSegments models, verbatim from app.py."""
    lines = (ROOT / "backends" / "pixeltable" / "app.py").read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("class Calls("))
    end = next(i for i, line in enumerate(lines) if "__indexes__" in line)
    return "\n".join(lines[start : end + 1])


def evolve_table(evolve: dict, m: dict) -> str:
    a, r = evolve["add_field"], evolve["rerun_step"]

    def steps(entry: dict) -> str:
        return "<br>".join(f"{s['step']} ({s['sec']:.0f}s)" for s in entry["steps"])

    rows = [
        ["**Add `topics` to live data**", "", ""],
        ["Lines written (backend)", str(a["reference"]["cost"]["lines_added"]), str(a["pixeltable"]["cost"]["lines_added"])],
        ["Files touched (backend)", str(a["reference"]["cost"]["files_touched"]), str(a["pixeltable"]["cost"]["files_touched"])],
        ["Operator steps", steps(a["reference"]), steps(a["pixeltable"])],
        ["Wall time", f"{a['reference']['total_sec']:.0f}s", f"{a['pixeltable']['total_sec']:.0f}s"],
        [f"Existing calls with topics (of {a['reference']['rows']})", str(a["reference"]["rows_with_topics"]), str(a["pixeltable"]["rows_with_topics"])],
        ["New uploads get topics", yes(a["reference"]["new_call_has_topics"]), yes(a["pixeltable"]["new_call_has_topics"])],
        ["**Re-run only the summary after a prompt change**", "", ""],
        ["Lines written (backend)", str(r["reference"]["cost"]["lines_added"]), str(r["pixeltable"]["cost"]["lines_added"])],
        ["Operator steps", steps(r["reference"]), steps(r["pixeltable"])],
        ["Wall time", f"{r['reference']['total_sec']:.0f}s", f"{r['pixeltable']['total_sec']:.0f}s"],
        [f"Summaries changed (of {r['reference']['rows']})", str(r["reference"]["summaries_changed"]), str(r["pixeltable"]["summaries_changed"])],
        ["Transcripts untouched", str(r["reference"]["transcripts_untouched"]), str(r["pixeltable"]["transcripts_untouched"])],
        ["Coaching comment still anchored", yes(r["reference"]["probe_comment_still_anchored"]), yes(r["pixeltable"]["probe_comment_still_anchored"])],
    ]
    if "reference_full_reprocess" in r:
        f = r["reference_full_reprocess"]
        rows += [
            ["**Reference without new code: re-queue `process_call`**", "", ""],
            ["Wall time", f"{f['total_sec']:.0f}s", ""],
            ["Transcripts untouched", str(f["transcripts_untouched"]), ""],
            ["Coaching comment still anchored", yes(f["probe_comment_still_anchored"]), ""],
        ]
    if "recover" in evolve:
        v = evolve["recover"]
        resume_loc = m["reference"]["file_breakdown"].get("backends/reference/worker/tasks/resume_call.py")
        rows += [
            ["**Recover from an LLM outage during processing**", "", ""],
            ["State after the outage", f"{v['reference']['status_after_outage']}, {v['reference']['segments_kept_through_outage']} segments kept",
             f"{v['pixeltable']['status_after_outage']}, {v['pixeltable']['segments_kept_through_outage']} segments kept"],
            ["Where the error is recorded", "the call's `status` and `error_message`",
             "`errormsg` on " + ", ".join(f"`{c}`" for c in v["pixeltable"]["failed_cells"])],
            ["Recovery code that had to exist", f"{cell(resume_loc)} lines (`resume_call.py`)", "0 lines"],
            ["Operator steps", steps(v["reference"]), steps(v["pixeltable"])],
            ["Wall time", f"{v['reference']['total_sec']:.0f}s", f"{v['pixeltable']['total_sec']:.0f}s"],
            ["Completed, transcript untouched", yes(v["reference"]["status_after_recovery"] == "completed" and v["reference"]["transcript_untouched"]),
             yes(v["pixeltable"]["status_after_recovery"] == "completed" and v["pixeltable"]["transcript_untouched"])],
            ["Searchable again", yes(v["reference"]["searchable_after_recovery"]), yes(v["pixeltable"]["searchable_after_recovery"])],
        ]  # fmt: skip
    return table(["", "Reference", "Pixeltable"], rows)


def yes(v: bool) -> str:
    return "yes" if v else "**no**"


# ------------------------------------------------------------------------ output


def render() -> dict[Path, str]:
    metrics = json.loads((RESULTS / "metrics.json").read_text())
    bench = json.loads((RESULTS / "benchmarks.json").read_text()) if (RESULTS / "benchmarks.json").is_file() else None
    evolve = json.loads((RESULTS / "evolve.json").read_text()) if (RESULTS / "evolve.json").is_file() else None
    if evolve:
        shared = evolve["add_field"]["shared"]
        shared["cost_label"] = f"{shared['lines_added']} lines in {shared['files_touched']} files"

    files: dict[Path, str] = {}
    parts, y = code_chart(metrics)
    if evolve:
        more, y = evolve_chart(evolve, y)
        parts += more
    files[RESULTS / "summary.svg"] = svg(parts, y)
    if bench and "pipeline" in bench:
        parts, y = pipeline_chart(bench, 0)
        files[RESULTS / "pipeline.svg"] = svg(parts, y)
    if bench and "reads" in bench:
        parts, y = reads_chart(bench, 0)
        files[RESULTS / "reads.svg"] = svg(parts, y)

    generated = tables(metrics, bench, evolve)
    for doc in DOCS:
        if not doc.is_file():
            continue
        original = doc.read_text()
        updated = original
        for name, body in generated.items():
            # the body between the markers may be empty, as in a doc that was never rendered
            pattern = re.compile(rf"(<!-- results:{name} -->\n)(?:.*?\n)?(<!-- /results:{name} -->)", re.S)
            updated = pattern.sub(lambda m, body=body: m.group(1) + body + "\n" + m.group(2), updated)
        files[doc] = updated
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, content in render().items():
        current = path.read_text() if path.is_file() else None
        if current == content:
            continue
        if args.check:
            stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(content)
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("stale, run `uv run python scripts/render_results.py`:\n  " + "\n  ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
