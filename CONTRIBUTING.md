# Contributing

This repo implements one call-intelligence product twice and measures the difference: a vibe-coded open-source stack (FastAPI, Celery, Redis, Postgres with pgvector, Alembic) and Pixeltable. The value is the contrast, so the rules below protect it. What is measured and how is in [compare/METHODOLOGY.md](compare/METHODOLOGY.md).

## Rules that are easy to break

1. **Never type a number into a doc.** Numbers come from `compare/results/*.json` and are written into the docs by `scripts/render_results.py` between `<!-- results:... -->` markers. CI fails when they drift.
2. **A metric with no pattern for a backend renders `n/a`, never `0`.** Pixeltable has no migration files because it has no migrations, not because it wrote zero of them.
3. **One contract.** Both backends serve [`shared/call_center_api/schemas.py`](shared/call_center_api/schemas.py) to one React client. A change to the contract is a change to both backends, the client and the gates.
4. **Hold each backend to its platform's own idioms.** Pixeltable is one `app.py` applied with `pxt schema update` and served with `pxt service update`, as its docs prescribe. If either side is more verbose than its platform requires, that is our bug, not its cost.
5. **Fix a defect on whichever side has it.** Neither backend wins a comparison on a bug. Record the fix in [METHODOLOGY.md](compare/METHODOLOGY.md#fixed-in-this-pass).
6. **Do not claim behavior you did not observe.** Timings come from `scripts/benchmark.py`, change costs from `scripts/bench_evolve.py`, and a failed run is published, not retried away. The exception is a run the harness broke: fix the harness, record the fix in METHODOLOGY.md, and re-run in full.

## Layout

```
backends/
  pixeltable/app.py       # schema, pipeline, queries and HTTP (pxt schema / pxt service)
  pixeltable/functions.py # the UDFs app.py calls
  reference/app/          # FastAPI routers, SQLAlchemy models, services
  reference/worker/       # Celery app and tasks
  reference/alembic/      # migrations
shared/call_center_api/   # contract, prompts, parsers, speaker labeling (both backends import it)
frontend/                 # one React UI, one API client
compare/
  results/                # committed measurements and the charts rendered from them
  evolve/                 # patches bench_evolve.py applies, times and reverts
  fixtures/               # 10 recordings across 4 verticals; videos are fetched
  reports/                # gate output (gitignored)
scripts/                  # run_compare.sh, seed, gates, benchmarks, metrics, renderer
```

## Development setup

Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node.js 20+, Docker, and a Hugging Face token with the [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) terms accepted. The current Pixeltable lock resolves 0.7.15; historical benchmark JSON retains the release actually measured. Start with the [core lesson](README.md#run-the-first-lesson): the same backend requests one summary enrichment in an isolated catalog, and optional enrichment fields remain null. `examples/extend_call.py` demonstrates selective recompute without model calls; declare persistent product fields in `TableModel` rather than leaving manual catalog changes behind.

```bash
cp .env.example .env                                  # set HF_TOKEN
docker compose up -d && docker compose exec ollama ollama pull llama3.1
uv sync --frozen && (cd backends/pixeltable && uv sync --frozen) && (cd backends/reference && uv sync --frozen) && (cd frontend && npm ci)
./scripts/run_compare.sh                              # both APIs, the Celery worker and both UIs
./scripts/run_compare.sh seed                         # reset both stores, ingest the 10 fixtures
```

`run_compare.sh` exports `.env` before any `pxt` command, because the pxt daemon reads its configuration once at startup. It gives the daemon a port of its own (`PXT_PORT`, default 22090): `pxt` replaces a daemon that serves another project on its port.

## Checks

Without services, as CI runs them:

```bash
(cd shared && uv run --with pytest python -m pytest tests -q)
(cd backends/pixeltable && uv run --frozen --with pytest python -m pytest tests/test_api_contract.py -q)
(cd backends/pixeltable && PXT_ENRICHMENT_PROFILE=core uv run --frozen --with pytest python -m pytest tests/test_api_contract.py -q -k 'core_profile or extension')
(cd backends/reference && uv run --frozen --with pytest python -m pytest tests/test_contract.py -q)
uvx ruff@0.16.9 check . && uv run --with pytest python -m pytest scripts/tests -q
uv run python scripts/metrics.py --check
uv run python scripts/render_results.py --check
(cd frontend && npx tsc -b && npx oxlint)
```

With both stacks up and seeded:

```bash
uv run python scripts/compare_all.py                  # gates: parity on the seeded fixtures, then mutations
uv run python scripts/benchmark.py                    # timings -> compare/results/benchmarks.json
uv run python scripts/bench_evolve.py --full-reprocess  # new invocation report -> compare/reports/evolve/; re-seed after
uv run python scripts/metrics.py && uv run python scripts/render_results.py
(cd backends/pixeltable && PXT_INSERT_SMOKE=1 uv run python -m unittest tests.test_insert_smoke -v)
```

Run the scripts through the environment `run_compare.sh` sets up: they read `REF_API`, `PXT_API`, `PIXELTABLE_HOME` and `PXT_PORT` from it. Seeding warms model processes. The benchmark's initial call warms the current process state and is excluded from the medians; a dedicated cold-start experiment must separately record process restarts and prewarming.

Evolution runs never merge with or overwrite `compare/results/evolve.json`. Each invocation reserves a new report, records source/setup/model/fixture/patch identity, and gives each attempted experiment its own status and timestamps. `--only` records only its selected experiment; failures retain errors without old success metrics. Review a complete compatible run before deliberately replacing published results and regenerating documents. Partial reports are observations, not a publication of all three experiments.

| Script | Does |
|---|---|
| `run_compare.sh` | start / seed / stop both stacks |
| `seed_compare.py` | fetch and validate fixtures, reset both stores, ingest the manifest |
| `compare_parity.py` | gate: same structure, transcripts, search, roster, filters and KPIs on both |
| `compare_mutations.py` | gate: comments and delete, verified down to each store |
| `compare_all.py` | both gates |
| `benchmark.py` | pipeline and read timings |
| `bench_evolve.py` | add a field; selectively rerun a step; recover from an outage; save a new invocation report under `compare/reports/evolve/` |
| `metrics.py` | code and architecture counts from source |
| `render_results.py` | charts and doc tables from `compare/results/` |
| `fetch_fixtures.py`, `prepare_fixture_media.py`, `generate_fixture_audio.py`, `validate_fixture_manifest.py` | fixture media |

## Making a change

1. Keep both backends on [compare/PIPELINE_SPEC.md](compare/PIPELINE_SPEC.md). A deliberate difference goes in [compare/CAPABILITY_PARITY.md](compare/CAPABILITY_PARITY.md).
2. Re-run the gates, then `metrics.py` and `render_results.py`, and commit the regenerated files.
3. If a timing or change cost could move, re-run `benchmark.py` or `bench_evolve.py` before publishing updated runtime claims. Source counts may be refreshed separately; label retained runtime measurements as historical. `benchmark.py` fingerprints source and refuses to merge sections measured from different dirty checkouts, and its warm-up call does not establish a verified cold start.

Out of scope for now: auth, rate limiting, multi-tenancy, backup and restore.
