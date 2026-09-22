#!/usr/bin/env python3
"""Compare architectural patterns between reference and Pixeltable backends."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.compare_common import PIXELTABLE, REFERENCE, print_section, print_table, write_report

PATTERNS = [
    {
        "area": "Pipeline orchestration",
        "reference": "Celery task chain (transcribe → diarize → enrich → embed)",
        "pixeltable": "Declarative computed columns + embedding index",
        "reference_files": ["worker/tasks/process_call.py"],
        "pixeltable_files": ["schema.py", "functions.py"],
    },
    {
        "area": "Persistence",
        "reference": "SQLAlchemy models + Alembic migrations + pgvector",
        "pixeltable": "Pixeltable tables/views + catalog versioning",
        "reference_files": ["app/models.py", "alembic/versions/"],
        "pixeltable_files": ["schema.py"],
    },
    {
        "area": "API layer",
        "reference": "FastAPI routers + shared Pydantic schemas",
        "pixeltable": "FastAPIRouter + @pxt.query (native contract, {rows} wrapper)",
        "reference_files": ["app/routers/"],
        "pixeltable_files": ["queries.py", "routers/native.py", "routers/search.py"],
        "shared_files": ["shared/call_center_api/schemas.py"],
    },
    {
        "area": "Search",
        "reference": "Postgres ILIKE + pgvector cosine in SQLAlchemy",
        "pixeltable": "contains() + column.similarity() embedding index",
        "reference_files": ["app/routers/search.py"],
        "pixeltable_files": ["routers/search.py"],
    },
    {
        "area": "Video ingest",
        "reference": "ffmpeg extract → audio_path → Celery",
        "pixeltable": "video column → extract_audio computed column",
        "reference_files": ["app/services/video.py", "app/services/storage.py"],
        "pixeltable_files": ["schema.py", "routers/native.py"],
    },
    {
        "area": "Async / concurrency",
        "reference": "Redis broker + Celery worker processes",
        "pixeltable": "Inline computed column evaluation on read/insert",
        "reference_files": ["worker/celery_app.py"],
        "pixeltable_files": ["functions.py"],
    },
    {
        "area": "Observability",
        "reference": "Call.status field + Celery logs + /api/health",
        "pixeltable": "pipeline_status column + errormsg enrichment + /api/health",
        "reference_files": ["app/services/health.py"],
        "pixeltable_files": ["services/health.py", "functions.py"],
    },
    {
        "area": "Lineage / view inheritance",
        "reference": "SQL JOIN Call ↔ TranscriptSegment in search",
        "pixeltable": "transcript_segments view inherits call metadata",
        "reference_files": ["app/routers/search.py"],
        "pixeltable_files": ["schema.py", "routers/search.py"],
    },
    {
        "area": "Incremental compute",
        "reference": "Re-run Celery task to reprocess a call",
        "pixeltable": "Computed columns + optional recompute_columns (not exposed)",
        "reference_files": ["worker/tasks/process_call.py"],
        "pixeltable_files": ["schema.py", "functions.py"],
    },
    {
        "area": "Versioning",
        "reference": "Alembic schema migrations",
        "pixeltable": "Catalog versioning + snapshots (not used in app)",
        "reference_files": ["alembic/versions/"],
        "pixeltable_files": ["schema.py"],
    },
    {
        "area": "Background upload",
        "reference": "202 fast + Celery (process_call.delay)",
        "pixeltable": "ThreadPool upload + @pxt.query reads; reference-compatible multipart /upload",
        "reference_files": ["app/routers/calls.py", "worker/tasks/process_call.py"],
        "pixeltable_files": ["routers/native.py", "queries.py"],
    },
]


def file_exists(base: Path, rel: str) -> bool:
    path = base / rel
    return path.is_file() or path.is_dir()


def main() -> int:
    print_section("Architecture Patterns")
    rows = []
    shared_root = ROOT / "shared"
    for item in PATTERNS:
        ref_ok = all(file_exists(REFERENCE.code_dir, f) for f in item["reference_files"])
        pxt_ok = all(file_exists(PIXELTABLE.code_dir, f) for f in item["pixeltable_files"])
        shared_ok = all(file_exists(shared_root, f.removeprefix("shared/")) for f in item.get("shared_files", []))
        if item.get("shared_files"):
            ref_ok = ref_ok and shared_ok
            pxt_ok = pxt_ok and shared_ok
        rows.append([item["area"], "yes" if ref_ok else "missing", "yes" if pxt_ok else "missing"])
        print(f"\n{item['area']}")
        print(f"  Reference:  {item['reference']}")
        print(f"  Pixeltable: {item['pixeltable']}")

    print_table(["Area", "Reference impl", "Pixeltable impl"], rows)
    path = write_report("patterns", {"patterns": PATTERNS})
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
