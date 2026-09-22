# Contributing

This repo exists to implement the **same call-center product** on two backends and verify they stay in parity. Neither backend is declared “production winner” — the goal is a fair side-by-side comparison with automated gates.

For how to run and use the app, see [README.md](README.md).

## Repository layout

```
sample-app-call-intelligence/
├── frontend/                 # shared React UI
├── backends/
│   ├── reference/            # Celery + Postgres + pgvector (:8001)
│   └── pixeltable/           # Pixeltable computed columns (:8000)
├── shared/
│   └── call_center_api/      # shared API contract: schemas, vertical prompts, enrichment parsers, constants
├── compare/
│   ├── fixtures/             # canonical WAV + manifest; mp4s fetched
│   ├── FEATURE_PARITY.md     # UI/API audit
│   ├── CAPABILITY_PARITY.md  # platform capability matrix
│   ├── PIPELINE_SPEC.md      # pipeline contract
│   ├── BACKEND_MAPPING.md    # Pixeltable ↔ Reference lifecycle + code map
│   ├── WHY_PIXELTABLE.md     # L1 measured contrast only
│   └── reports/              # generated JSON (gitignored)
├── scripts/                  # run_compare, seed, parity, benchmarks
├── data/                     # local durable stores (gitignored)
└── docker-compose.yml        # Postgres, Redis, Ollama
```

## Development setup

**Prerequisites**

- Python 3.11+, [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- Docker
- HuggingFace token for pyannote diarization

```bash
cp .env.example .env
cp .env.example backends/reference/.env
cp .env.example backends/pixeltable/.env
# Edit HF_TOKEN in both backend .env files

docker compose up -d
docker compose exec ollama ollama pull llama3.1

uv sync
cd backends/pixeltable && uv sync
cd backends/reference && uv sync
cd frontend && npm install
```

## Side-by-side comparison workflow

```bash
chmod +x scripts/run_compare.sh
./scripts/run_compare.sh              # start both stacks
./scripts/run_compare.sh seed         # generate/prepare/fetch + reset DBs + upload 10 fixtures
uv run python scripts/compare_parity.py
./scripts/run_compare.sh stop
```

**Note:** Seeding uploads **10 fixtures** (6 audio + 4 video) to each backend, covering all four verticals. `./scripts/run_compare.sh seed` runs `generate_fixture_audio.py`, `fetch_fixtures.py`, `prepare_fixture_media.py`, and `validate_fixture_manifest.py` automatically. Upload HTTP calls return quickly on both stacks (202 + background processing); seeding then polls until pipelines complete — expect several minutes for video fixtures on first seed (default `TIMEOUT_SEC=1800` in the seed script). That poll cap is separate from Reference worker limits: `OLLAMA_TIMEOUT_SEC` (per LLM request) and `CELERY_TASK_*_TIME_LIMIT_SEC` (whole Celery task).

### Compare fixtures

| Vertical | Audio | Video |
|----------|-------|-------|
| call_center | `billing-inquiry-speech.wav`, `cancellation-request.wav` | `pursuit-happiness-video.mp4` |
| sales | `sales-discovery.wav` | `sales-demo-video.mp4` (copy) |
| podcast | `podcast-excerpt-audio.wav` (extract) | `lex-fridman-excerpt.mp4`, `travel-briefing.mp4` |
| interview | `interview-behavioral.wav` | `interview-session.mp4` (copy) |

| Type | Scripts | Source |
|------|---------|--------|
| Synthetic audio | [`scripts/generate_fixture_audio.py`](scripts/generate_fixture_audio.py) | macOS `say` + ffmpeg (committed WAVs) |
| Downloaded video | [`scripts/fetch_fixtures.py`](scripts/fetch_fixtures.py) | Pixeltable docs resources (`sources.json`) |
| Derived media | [`scripts/prepare_fixture_media.py`](scripts/prepare_fixture_media.py) | ffmpeg extract + MP4 copies |
| Manifest validation | [`scripts/validate_fixture_manifest.py`](scripts/validate_fixture_manifest.py) | Coverage matrix before seed |

Manifest: [`compare/fixtures/manifest.json`](compare/fixtures/manifest.json). Checksums: [`compare/fixtures/sources.json`](compare/fixtures/sources.json). Attribution: [`compare/fixtures/ATTRIBUTION.md`](compare/fixtures/ATTRIBUTION.md).

Downloaded and derived `*.mp4` files are gitignored. Committed WAVs stay in-repo. `./scripts/run_compare.sh seed` runs fetch and `prepare_fixture_media.py` before upload.

| Tab | URL | Backend |
|-----|-----|---------|
| Reference | http://localhost:**5173** | Celery + Postgres |
| Pixeltable | http://localhost:**5174** | Pixeltable |

Do **not** compare against http://localhost:8000 in the browser — that is the Pixeltable API (and optional SPA mount). The compare UI for Pixeltable is **5174**.

## Comparison scripts

| Script | What it measures |
|--------|------------------|
| `compare_setup.py` | Pixeltable schema verify + `/api/health` on both backends |
| `compare_parity.py` | Fixture parity (segments, sentiment, media, audio/video streams, search) |
| `compare_search.py` | Hybrid search hits and metadata |
| `compare_patterns.py` | Architecture pattern inventory (Celery vs computed columns, etc.) — informational |
| `compare_loc.py` | Lines of code by area (routers, pipeline, schemas) — informational |
| `compare_speed.py` | Read API latency (p50/p95); `--pipeline --fresh-pipeline` for upload accept + pipeline complete |
| `compare_data.py` | Postgres row counts, upload dir size, Pixeltable catalog stats |
| `compare_concurrency.py` | Parallel uploads (`--workers N`, `--wait` for pipeline completion) |
| `compare_observability.py` | Health, status distribution, KPIs, flagged calls, errors |
| `compare_mutations.py` | Coaching comments + call delete lifecycle (ephemeral uploads) |
| `compare_assess.py` | Human-readable assessment from report JSON |
| `demo_recompute.py` | Pixeltable incremental recompute demo (summary-only; transcription unchanged) |
| `demo_recompute_inner.py` | Catalog-side helper invoked by `demo_recompute.py` |
| `compare_all.py` | Run the suite; writes JSON to `compare/reports/` |
| `smoke_test.py` | Fresh upload E2E per backend — **recommended**, not a `compare_all` gate |
| `fetch_fixtures.py` | Download pinned video fixtures from `compare/fixtures/sources.json` |
| `generate_fixture_audio.py` | Generate synthetic sales/interview WAV fixtures |
| `prepare_fixture_media.py` | Extract podcast audio + create derived MP4 copies |
| `validate_fixture_manifest.py` | Assert vertical/media coverage and on-disk files |

**Compare helpers** (`scripts/lib/`):

| Module | Role |
|--------|------|
| `compare_common.py` | Shared HTTP helpers, report writer, upload/wait utilities |
| `pxt_api.py` | Normalize Pixeltable native JSON → reference-shaped dicts; `embed-ready` wait |

**`compare_all.py` gate sets**

| Mode | Gates (must exit 0) |
|------|---------------------|
| Default | `setup`, `parity`, `search`, `speed`, `data`, `observability` (+ informational `patterns`, `loc`) |
| `--full` | Default + `concurrency`, `speed_pipeline`, `mutations`, `recompute` |

**Gate tolerances / thresholds**

- `compare_speed.py`: pipeline wall-clock ratio Pixeltable/Reference must stay ≤ `PIPELINE_RATIO_MAX` (3.0) when `--pipeline --fresh-pipeline` is used.
- `compare_observability.py`: tolerates **≤1** failed *seeded* Reference call (LLM/video variance); Pixeltable seeded failures fail the gate.
- `compare_parity.py`: soft LLM theme checks are informational; video segment timing mismatches are noted but do not fail (WhisperX variance).

```bash
# Quick suite (no extra uploads)
uv run python scripts/compare_all.py

# Full suite after seed
./scripts/run_compare.sh seed
uv run python scripts/compare_all.py --full
uv run python scripts/compare_assess.py

# Include parallel upload benchmark (creates extra calls)
uv run python scripts/compare_all.py --with-concurrency

# Pipeline timing (fresh upload + two-phase metrics)
uv run python scripts/compare_speed.py --pipeline --fresh-pipeline
# All fixtures (slow)
uv run python scripts/compare_speed.py --pipeline --fresh-pipeline --pipeline-all

# Comment + delete lifecycle (does not modify seeded fixture IDs)
uv run python scripts/compare_mutations.py
uv run python scripts/compare_all.py --with-mutations
```

Reports land in `compare/reports/*.json` (setup, patterns, loc, speed, data, observability, concurrency, summary, assess).

## What should match vs differ

| Should match | Expected to differ |
|--------------|-------------------|
| UI layout, upload form, roster, waveform flags, sidebar | Exact LLM summary/QA scores |
| Segment count, speaker labels, category presence | Call/segment UUIDs |
| Hybrid search returns hits for `"billing"` | Processing speed, status timing |

Correctness gates: `compare_parity.py`, `compare_search.py`.

## Data directories

`./scripts/run_compare.sh` exports repo-local paths so both backends survive restarts:

| Path | Env var | Backend | Contents |
|------|---------|---------|----------|
| `data/pixeltable/` | `PIXELTABLE_HOME` | Pixeltable | Catalog, media blobs, embedding index |
| `data/reference/uploads/` | `UPLOAD_DIR` | Reference | Uploaded audio/video files |
| Docker volume `postgres_data` | `DATABASE_URL` | Reference | Postgres + pgvector |
| Docker volume `ollama_data` | `OLLAMA_HOST` | Chat enrichment (llama3.1) |

These dirs are gitignored. `./scripts/run_compare.sh stop` kills processes but **keeps data**. To reset fixtures: `./scripts/run_compare.sh seed`.

Copy [.env.example](.env.example) and set `PIXELTABLE_HOME` / `UPLOAD_DIR` if running backends outside `run_compare.sh`.

## Health endpoint

Both APIs expose `GET /api/health` with dependency checks:

```json
{
  "status": "ok",
  "backend": "reference",
  "checks": {
    "postgres": {"ok": true},
    "redis": {"ok": true},
    "celery": {"ok": true, "detail": "1 worker(s): ref@host"},
    "ollama": {"ok": true, "detail": "Models available at http://localhost:11434"},
    "embed_model": {"ok": true, "detail": "all-mpnet-base-v2"}
  }
}
```

- **`status: ok`** — all checks passed
- **`status: degraded`** — API is up but a dependency is missing (HTTP 200; compare scripts report which checks failed)

Pixeltable checks: `catalog`, `ollama`, `embed_model`, `pipeline`.

Reference checks: `postgres`, `redis`, `celery`, `ollama`, `embed_model`.

## Known intentional differences

These are **architecture differences**, not parity bugs:

| Topic | Reference | Pixeltable |
|-------|-----------|------------|
| Upload HTTP accept | ~0.1s (202 + Celery) | ~0.1s (202 + background insert) |
| Pipeline completion | Poll until `completed` | Poll until `completed` (+ `/embed-ready` in seed/compare) |
| Read API latency | Often faster (SQL ORM) | Often slower (catalog + view); see `compare/reports/assess.json` |
| LLM output text | May differ slightly | May differ slightly |
| Wire JSON shape | Shared Pydantic schemas | Catalog-native; UI + `pxt_api.py` adapt |

Upload semantics: both backends return **202 immediately** and process in the background (Reference: Celery; Pixeltable: thread-pool insert + computed columns). Speed benchmarks report **upload accept** and **pipeline complete** separately — see `compare/reports/speed.json` from `compare_speed.py --pipeline --fresh-pipeline`.

More detail: [compare/CAPABILITY_PARITY.md](compare/CAPABILITY_PARITY.md).

## Recommended verification

After backend or UI changes:

```bash
./scripts/run_compare.sh seed
uv run python scripts/compare_all.py --full
uv run python scripts/compare_assess.py
uv run python scripts/verify_setup.py
uv run python scripts/smoke_test.py --backend both   # recommended; not part of compare_all gates
```

`smoke_test.py` exercises a fresh upload end-to-end on each backend. It is listed in CAPABILITY_PARITY for upload coverage but is **not** wired into `compare_all.py` (keeps `--full` runtime bounded). Run it after upload-path changes.

## Architecture

```
compare/fixtures → seed_compare.py
                      ├→ Reference API (:8001) → Celery → Postgres
                      └→ Pixeltable API (:8000) → computed columns

frontend/ → :5173 (reference) | :5174 (pixeltable)
```

## Shared API contract

Reference serves [`shared/call_center_api/schemas.py`](shared/call_center_api/schemas.py). Pixeltable serves catalog-native JSON; the Pixeltable UI adapts in [`frontend/src/api/client.pixeltable.ts`](frontend/src/api/client.pixeltable.ts), and compare scripts normalize via [`scripts/lib/pxt_api.py`](scripts/lib/pxt_api.py) + [`compare/pxt_api_mapping.json`](compare/pxt_api_mapping.json). See [compare/CAPABILITY_PARITY.md](compare/CAPABILITY_PARITY.md) §F.

Pipeline transforms: [compare/PIPELINE_SPEC.md](compare/PIPELINE_SPEC.md). Value-add vs vanilla catch-up: CAPABILITY_PARITY §C / §H / §I.

## Making changes

1. Keep both backends aligned with [compare/PIPELINE_SPEC.md](compare/PIPELINE_SPEC.md) unless the change is an **intentional** comparison difference — then update [compare/CAPABILITY_PARITY.md](compare/CAPABILITY_PARITY.md).
2. Update [compare/FEATURE_PARITY.md](compare/FEATURE_PARITY.md) when adding or changing UI/API behavior.
3. Run the recommended verification suite before opening a PR.
4. Extend compare scripts when adding new parity gates (see existing scripts in `scripts/`).

## Individual backends

**Pixeltable only:**

```bash
cd backends/pixeltable
RESET_SCHEMA=true uv run python schema.py
uv run uvicorn main:app --host 127.0.0.1 --port 8000
cd ../../frontend && VITE_API_PORT=8000 VITE_DEV_PORT=5174 VITE_BACKEND=pixeltable npm run dev
```

**Pixeltable providers:** Pixeltable 0.7.8 `TableModel` in [`schema.py`](backends/pixeltable/schema.py) (`pxt.model_base()` + `create_all`). Ollama via built-in `ollama.chat` computed columns + `vertical_prompt` / `parse_*` UDFs. Embeddings via native `sentence_transformer.using(model_id=..., normalize_embeddings=True)` (ST `>=5.4,<6`). See [compare/PIPELINE_SPEC.md](compare/PIPELINE_SPEC.md).

Insert smoke test (requires schema + Ollama + WhisperX):

```bash
cd backends/pixeltable
PXT_INSERT_SMOKE=1 uv run python -m unittest tests.test_insert_smoke -v
```

**Reference only:**

```bash
docker compose up -d
cd backends/reference && uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
uv run celery -A worker.celery_app worker -l info
cd ../../frontend && VITE_API_PORT=8001 VITE_DEV_PORT=5173 npm run dev
```

## Advocacy docs

Public contrast lives in [compare/WHY_PIXELTABLE.md](compare/WHY_PIXELTABLE.md) and cites **measured-in-repo** numbers only. Do not add competitor per-minute prices or FTE estimates.

## Deferred (not in scope yet)

Auth, rate limiting, backup/restore runbooks, systemd/self-host, Cloudflare tunnel — revisit when moving beyond local comparison dev.
