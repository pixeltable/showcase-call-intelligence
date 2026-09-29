#!/usr/bin/env python3
"""Measure the two backends from source. Writes compare/results/metrics.json.

    uv run python scripts/metrics.py            # print and write
    uv run python scripts/metrics.py --check    # exit 1 if the committed JSON is stale

Everything in MEASURED comes from the files on disk. CLASSIFIED is written by hand and
reported as hand-classified. A metric with no pattern for a backend is None, rendered
`n/a`, never 0: a structural zero printed as a measurement is not a measurement.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "compare" / "results" / "metrics.json"

LINE_COMMENTS = {".py": ("#",), ".ts": ("//",), ".tsx": ("//",), ".toml": ("#",), ".ini": ("#", ";"), ".yml": ("#",)}
BLOCK_COMMENTS = {".ts": ("/*", "*/"), ".tsx": ("/*", "*/")}
DOCSTRING_SUFFIXES = {".py"}

# Code each backend owns. Tests, lock files and the shared package are counted elsewhere.
IMPLEMENTATIONS: dict[str, dict] = {
    "pixeltable": {
        "dir": ROOT / "backends" / "pixeltable",
        "app_globs": ["**/*.py"],
        "exclude_parts": {".venv", "__pycache__", "tests"},
        "config_files": ["backends/pixeltable/pyproject.toml"],
        # Files outside the backend dir that exist only because of this backend.
        "extra_app_files": [],
    },
    "reference": {
        "dir": ROOT / "backends" / "reference",
        "app_globs": ["**/*.py"],
        "exclude_parts": {".venv", "__pycache__", "tests"},
        "config_files": ["backends/reference/pyproject.toml", "backends/reference/alembic.ini"],
        "extra_app_files": [],
    },
}

# Imported by both backends: counted once, charged to neither.
SHARED = {
    "dir": ROOT / "shared" / "call_center_api",
    "app_globs": ["*.py"],
    # fixture_manifest.py validates compare fixtures; no backend imports it.
    "exclude_names": {"fixture_manifest.py"},
}

# Regexes over comment-free code. Read them; argue with them. `tables` and `views` on the
# Pixeltable side are counted from the AST (see _table_models) because a class header spans lines.
PATTERNS: dict[str, dict[str, str]] = {
    "pixeltable": {
        "vector_indexes": r"pxt\.EmbeddingIndex\(",
        "routes_hand_written": r"^@(?:router|app|api)\.(?:get|post|put|patch|delete)\(",
        "routes_declared": r"\.add_(?:query|insert|update|delete|compute)_route\(",
        "orchestration_hops": r"\.insert\(|\.collect\(\)|\.delete\(|pxt\.get_table\(|\.recompute_columns\(",
    },
    "reference": {
        "tables": r"__tablename__\s*=",
        "vector_indexes": r"USING hnsw",
        "migrations": r"^revision(?::\s*str)?\s*=",
        "task_queue_tasks": r"@celery_app\.task\(",
        "status_writes": r"\bcall\.status\s*=",
        "routes_hand_written": r"^@(?:router|app)\.(?:get|post|put|patch|delete)\(",
        "orchestration_hops": (
            r"\.delay\(|\bdb\.commit\(\)|\bdb\.add\(|\bdb\.query\(|\bdb\.get\(|\bdb\.delete\(|\bconn\.execute\("
        ),
    },
}

# Hand-classified: which concern each file (or section of app.py, split at its `# ---- name` headers)
# serves. The line counts under each concern are measured; the grouping is a judgment, labelled as such.
CONCERNS: dict[str, dict[str, list[str]]] = {
    "reference": {
        "Schema and pipeline / schema and migrations": ["app/models.py", "app/database.py", "alembic/env.py",
                                                         "alembic/versions/*.py"],
        "Schema and pipeline / orchestration and status": ["worker/celery_app.py", "worker/tasks/process_call.py",
                                                            "worker/tasks/__init__.py"],
        "Schema and pipeline / model and media wrappers": ["app/services/whisperx_service.py", "app/services/ollama_client.py",
                                                            "app/services/embed_service.py", "app/services/video.py",
                                                            "app/services/diarization.py"],
        "Repair tooling": ["worker/tasks/resume_call.py", "worker/tasks/embed_maintenance.py", "app/routers/admin.py"],
        "Queries and HTTP": ["app/routers/calls.py", "app/routers/search.py", "app/routers/comments.py",
                             "app/services/storage.py", "app/services/health.py", "app/main.py"],
        "Settings (config.py)": ["app/config.py"],
    },
    "pixeltable": {
        "Schema and pipeline": ["app.py::", "app.py::the pipeline", "functions.py"],
        "Queries and HTTP": ["app.py::queries", "app.py::API"],
        "Settings (config.py)": ["config.py"],
    },
}  # fmt: skip
SECTION_RE = re.compile(r"^# -{8,} ?(.*?)\s*$")

# Hand-classified: true of the code, but no regex derives it.
CLASSIFIED: dict[str, dict] = {
    "pixeltable": {
        "processes_to_run": ["pxt service (the pxt daemon and its embedded Postgres start with it)"],
        "work_runs_on_insert_from_any_writer": True,
        "new_column_backfills_existing_rows": True,
        "table_versions_and_revert": True,
        "per_cell_errors": True,
        "intermediate_progress_visible": False,
    },
    "reference": {
        "processes_to_run": ["uvicorn API", "Celery worker", "Postgres with pgvector", "Redis"],
        "work_runs_on_insert_from_any_writer": False,
        "new_column_backfills_existing_rows": False,
        "table_versions_and_revert": False,
        "per_cell_errors": False,
        "intermediate_progress_visible": True,
    },
}


@dataclass
class Metrics:
    app_loc: int = 0
    app_files: int = 0
    config_loc: int = 0
    file_breakdown: dict[str, int] = field(default_factory=dict)
    tables: int | None = None
    views: int | None = None
    vector_indexes: int | None = None
    migrations: int | None = None
    task_queue_tasks: int | None = None
    status_writes: int | None = None
    routes_hand_written: int | None = None
    routes_declared: int | None = None
    orchestration_hops: int | None = None
    by_concern: dict[str, int] = field(default_factory=dict)
    classified: dict = field(default_factory=dict)


def code_lines_in(text: str, suffix: str) -> list[str]:
    """Non-blank lines that are not comments or Python docstrings."""
    markers = LINE_COMMENTS.get(suffix, ())
    block = BLOCK_COMMENTS.get(suffix)
    lines: list[str] = []
    in_block = False
    in_doc: str | None = None
    prev = ""
    for raw in text.splitlines():
        line = raw.strip()
        if in_block:
            if block and block[1] in line:
                in_block = False
            continue
        if in_doc:
            if in_doc in line:
                in_doc = None
            continue
        if not line:
            continue
        if block and line.startswith(block[0]):
            in_block = block[1] not in line[len(block[0]) :]
            continue
        if any(line.startswith(m) for m in markers):
            continue
        if suffix in DOCSTRING_SUFFIXES and _starts_docstring(line, prev):
            quote = line[:3]
            if line.count(quote) == 1:
                in_doc = quote
            continue
        lines.append(line)
        prev = line
    return lines


def _starts_docstring(line: str, prev: str) -> bool:
    """A bare string literal opening a module, class or def body is a docstring, not code."""
    if not line.startswith(('"""', "'''")):
        return False
    return prev == "" or prev.endswith(":")


def code_lines(path: Path) -> list[str]:
    try:
        return code_lines_in(path.read_text(encoding="utf-8"), path.suffix)
    except OSError:
        return []


def _source_files(root: Path, globs: list[str], exclude_parts: set[str], exclude_names: set[str]) -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            rel_parts = path.relative_to(root).parts
            if path.is_file() and not (set(rel_parts) & exclude_parts) and path.name not in exclude_names:
                seen[path] = None
    return list(seen)


def collect(name: str, config: dict) -> Metrics:
    metrics = Metrics(classified=CLASSIFIED.get(name, {}))
    root: Path = config["dir"]
    files = _source_files(root, config["app_globs"], config["exclude_parts"], set())
    files += [ROOT / rel for rel in config["extra_app_files"]]
    for path in files:
        loc = len(code_lines(path))
        if loc == 0:
            continue
        metrics.file_breakdown[str(path.relative_to(ROOT))] = loc
        metrics.app_loc += loc
        metrics.app_files += 1
    for rel in config["config_files"]:
        metrics.config_loc += len(code_lines(ROOT / rel))
    code = {path: "\n".join(code_lines(path)) for path in files}
    for metric, pattern in PATTERNS.get(name, {}).items():
        count = sum(len(re.findall(pattern, text, re.MULTILINE)) for text in code.values())
        setattr(metrics, metric, count)
    if name == "pixeltable":
        metrics.tables, metrics.views = _table_models(files)
    metrics.by_concern = _by_concern(root, CONCERNS.get(name, {}))
    unclassified = metrics.app_loc - sum(metrics.by_concern.values())
    if unclassified:
        metrics.by_concern["Unclassified"] = unclassified
    return metrics


def _sections(path: Path) -> dict[str, int]:
    """Code lines per `# ---- name` section; lines before the first header go under ''."""
    counts: dict[str, list[str]] = {"": []}
    current = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = SECTION_RE.match(raw.strip())
        if match:
            current = match.group(1)
            counts.setdefault(current, [])
            continue
        counts[current].append(raw)
    return {k: len(code_lines_in("\n".join(v), path.suffix)) for k, v in counts.items()}


def _by_concern(root: Path, concerns: dict[str, list[str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for concern, patterns in concerns.items():
        total = 0
        for pattern in patterns:
            file_part, _, section = pattern.partition("::")
            for path in sorted(root.glob(file_part)):
                total += _sections(path).get(section, 0) if "::" in pattern else len(code_lines(path))
        out[concern] = total
    return out


def _table_models(files: list[Path]) -> tuple[int, int]:
    """(tables, views): classes subclassing TableModel, split on whether they pass base=."""
    tables = views = 0
    for path in files:
        if path.suffix != ".py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(b, ast.Name) and b.id == "TableModel" for b in node.bases):
                continue
            if any(k.arg == "base" for k in node.keywords):
                views += 1
            else:
                tables += 1
    return tables, views


def collect_shared() -> dict:
    files = _source_files(SHARED["dir"], SHARED["app_globs"], {"__pycache__"}, SHARED["exclude_names"])
    breakdown = {str(p.relative_to(ROOT)): len(code_lines(p)) for p in files}
    breakdown = {k: v for k, v in breakdown.items() if v}
    return {"app_loc": sum(breakdown.values()), "app_files": len(breakdown), "file_breakdown": breakdown}


def collect_all() -> dict:
    return {
        "backends": {name: asdict(collect(name, cfg)) for name, cfg in IMPLEMENTATIONS.items()},
        "shared": collect_shared(),
        "patterns": PATTERNS,
    }


ROWS = [
    ("App LOC (non-blank, non-comment)", "app_loc"),
    ("App files", "app_files"),
    ("Project config LOC", "config_loc"),
    ("Tables", "tables"),
    ("Views", "views"),
    ("Vector indexes", "vector_indexes"),
    ("Migration files", "migrations"),
    ("Task-queue tasks", "task_queue_tasks"),
    ("Status writes", "status_writes"),
    ("Routes with a hand-written handler", "routes_hand_written"),
    ("Routes declared from a query or table", "routes_declared"),
    ("Orchestration hops", "orchestration_hops"),
]


def render_table(result: dict) -> str:
    names = list(result["backends"])
    width = max(len(label) for label, _ in ROWS) + 2
    out = [f"{'Measured':<{width}}" + "".join(f"{n:>14}" for n in names)]
    out.append("-" * len(out[0]))
    for label, key in ROWS:
        cells = []
        for name in names:
            value = result["backends"][name][key]
            cells.append("n/a" if value is None else str(value))
        out.append(f"{label:<{width}}" + "".join(f"{c:>14}" for c in cells))
    out.append(f"\nShared package (both backends import it, charged to neither): {result['shared']['app_loc']} LOC")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Fail if compare/results/metrics.json is stale")
    args = parser.parse_args()

    result = collect_all()
    rendered = json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    print(render_table(result))
    if args.check:
        current = OUT.read_text() if OUT.is_file() else ""
        if current != rendered:
            print(f"\n{OUT.relative_to(ROOT)} is stale. Run: uv run python scripts/metrics.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered)
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
