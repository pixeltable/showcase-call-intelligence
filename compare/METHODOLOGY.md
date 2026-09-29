# Methodology

What this comparison measures, how, and where it is tilted. The rules for changing it are in [CONTRIBUTING.md](../CONTRIBUTING.md).

## What is compared

One product: upload a recording, extract audio from video, transcribe and diarize, label speakers, run five LLM enrichments, index every segment for keyword and semantic search, review, comment, delete. Two implementations:

- **Reference**: FastAPI, SQLAlchemy, Alembic, Celery, Redis, Postgres with pgvector. It began as a self-hosted Gong-style MVP written with an AI coding assistant, then was aligned with the Pixeltable pipeline so outputs compare: same WhisperX steps and parameters, same prompts and parsers ([`shared/call_center_api`](../shared/call_center_api)), same embedding model.
- **Pixeltable**: one application file, [`backends/pixeltable/app.py`](../backends/pixeltable/app.py), applied with `pxt schema update` and served with `pxt service update`, as Pixeltable's docs prescribe.

Held equal: the React UI and its single API client, the contract ([`schemas.py`](../shared/call_center_api/schemas.py)), the ten fixtures, the models (WhisperX `base` and pyannote 3.1 on CPU, one Ollama serving `llama3.1`, `all-mpnet-base-v2`), Python 3.12.7 and the ML packages (torch, WhisperX, pyannote, sentence-transformers at identical versions in both lock files), and concurrency: one call processed at a time on each side (one Celery worker process; one insert thread, which is also what Pixeltable's table lock allows).

## What is measured

| What | How | Artifact |
|---|---|---|
| Code | [`scripts/metrics.py`](../scripts/metrics.py): non-blank lines that are not comments or docstrings, per backend directory; tests and lock files excluded; the shared package counted once and charged to neither. Architecture counts are regexes over that code, listed in `PATTERNS`; a count with no pattern for a backend is `n/a`. | [`results/metrics.json`](results/metrics.json) |
| Correctness | [`compare_parity.py`](../scripts/compare_parity.py) on the seeded fixtures; [`compare_mutations.py`](../scripts/compare_mutations.py) on fresh uploads, checking each store directly after delete. | `reports/` (gitignored) |
| Pipeline time | [`benchmark.py`](../scripts/benchmark.py): upload to `completed`, polled every 0.5 s; one call in flight; every fixture on one backend then the other, order flipped each round; median of the rounds. Before each call Ollama reloads the model, untimed. One call per backend first, reported as the first call after start. | [`results/benchmarks.json`](results/benchmarks.json) |
| Read latency | same script: 5 warm-up then 50 requests per endpoint per backend, interleaved, over the seeded corpus; p50 and p95. | same |
| Change cost | [`bench_evolve.py`](../scripts/bench_evolve.py) applies each patch in [`evolve/`](evolve/), runs the operator steps, verifies over HTTP, and reverts. Lines are counted the way `metrics.py` counts code. | [`results/evolve.json`](results/evolve.json) |

`CLASSIFIED` in `metrics.py` holds what no regex derives (processes to run, whether a new column backfills existing rows, whether progress is visible), labelled as hand-classified wherever it appears.

## Environment of the published run

<!-- results:environment -->
Apple M4 Pro, 14 cores, 48 GB, Darwin 26.6.1; Python 3.12.7; Pixeltable 0.7.11, WhisperX 3.8.6, torch 2.8.0; Ollama 0.31.1 serving `llama3.1` (46e0c10c039e) in Docker (4 cpus, 8307830784 bytes). Pipeline measured 2026-09-28T20:34:30+00:00, reads 2026-09-28T22:24:37+00:00, at `b37a52a` with local changes.
<!-- /results:environment -->

Ollama runs in Docker Desktop's Linux VM, CPU only, as `docker-compose.yml` sets it up (flash attention and an 8-bit KV cache, which keep `llama3.1` at about 5 GB), so LLM calls dominate the pipeline time on both sides.

Ollama keeps the state of the prompts it has evaluated and reuses it for any later prompt that starts the same way. Both backends send byte-identical prompts for the same recording, so without a reset the second backend to process a recording skips most of the prompt work the first one paid for, and the cache keeps growing. `reset_llm()` in [`scripts/lib/client.py`](../scripts/lib/client.py) unloads and reloads the model; the benchmark, the seed and each backend's run in `bench_evolve.py` call it first, outside the timings. The VM is memory-bound: an out-of-memory kill of the model runner surfaces as HTTP 500 on both backends, which is also why only one call is in flight at a time.

## Where this is favourable to Pixeltable

1. Pixeltable sponsors this repo, and one author reviewed and fixed both backends in this pass.
2. The workload is media-heavy, which is what computed columns are for. A CRUD app would read differently.
3. The Reference was generated, not written by Celery and SQLAlchemy specialists. It passes the same gates, and its defects found in this pass were fixed, but its repair tooling (`resume_call.py`, `embed_maintenance.py`, `admin.py`) is what a generated stack grows, not what an expert would design.
4. Single tenant, no auth, no realtime, one machine: the cases where a managed Postgres, Celery's horizontal scaling or a message queue pay for themselves are out of frame.

## Where this is favourable to the Reference

1. Both sides process one call at a time. Celery scales out with `-c N` or more workers; Pixeltable's inserts into one table hold its lock for the whole computation, so a second insert waits.
2. The Reference shows each stage while a call is processed. Pixeltable shows `processing`, then the result.
3. The Reference's backfill task commits row by row. `pxt schema update` backfills a new column in one transaction with errors aborting, so one failing row rolls back the whole migration.

## Fixed in this pass

Defects found by reading and running both sides, fixed so neither side wins on a bug:

| Side | Defect | Fix |
|---|---|---|
| Reference | Any queue filter returned HTTP 500: `.filter()` after `.limit()` | filters first, `order_by` and `limit` last |
| Reference | Video uploads ran ffmpeg inside the upload request, so a "202 Accepted" waited on ffmpeg | extraction moved into the Celery task |
| Reference | Semantic hits had `score: null` | cosine similarity returned |
| Reference | Upload read the whole file into memory | streamed to disk |
| Pixeltable | `create_all()` at import, so `pxt schema update` could not load the file | one `app.py`, `pxt schema update` / `pxt service update` |
| Pixeltable | A stored `pipeline_status` column claimed stages it could never show | removed; status is `processing` until the row commits |
| Pixeltable | Private internals (`get_runtime().catalog.begin_xact`, `template_query._collect`) to run queries | plain queries and declared routes |
| Pixeltable | Five LLM calls ran on silent recordings | a null transcript skips them, as on the Reference |
| Pixeltable | A different wire shape, adapted by a Pixeltable-only frontend client and a compare-side normalizer | serves the shared contract; both adapters deleted |
| Pixeltable | Upload files were never deleted | removed with the call |
| Pixeltable | Search filtered on a Python UDF, so the vector search could not push its LIMIT to Postgres | SQL-expressible error filter |
| Pixeltable | Call detail, comments and keyword search built their query on every request, and building a query resolves the table once per selected expression | select lists built once per process and filtered per request, as declared routes do |
| UI | Pixeltable uploads never appeared, a comment reloaded the waveform, the highlight stopped following playback, a failed video left no player, dates differed by the browser's UTC offset | fixed in the shared components |
| Harness | The delete gate compared a UUID column to a string, counted 0 before and after, and passed | typed UUIDs; counts checked before and after |
| Harness | Fixture dates had aged out of the 7-day KPI window, so both KPI banners showed 0 and matched | the seed shifts the dates so the newest call lands an hour before the seed |
| Harness | Lines were counted raw, the shared package was added to both totals, and the Pixeltable-only adapters were not counted | `metrics.py` |
| Harness | "Parallel enrichment" and a stage-by-stage status were claimed for Pixeltable | both removed: `ollama.chat` is a synchronous UDF, so the five calls run one after another, and rows commit whole |
| Harness | Ollama answered repeated prompts from its cache, so in an earlier run each fixture's first call was its slowest on almost every fixture, and the medians timed cached prompts | Ollama reloads the model before every timed call |

## Pixeltable issues this comparison hit

- **`revert()` drops rows of an untouched view.** After an operation on a base table that does not touch its iterator view (for example `recompute_columns`), `revert()` also reverts the view's latest version, deleting the rows of the last insert. Reproduced on 0.7.11 with a short script and in this app, where it removed a call's segments and their embeddings. Undo is therefore not measured here. Reported as [pixeltable#1687](https://github.com/pixeltable/pixeltable/issues/1687).
- **Building a query costs a catalog lookup per selected expression.** In 0.7.11 each expression in a select list resolves its table version in its own metadata transaction, so a handler that builds a 20-column query spends most of the request before Postgres runs anything. Declared routes build their query once. The hand-written handlers here build their select list once per process (`detail_query()` in `app.py`); semantic search cannot, because its score column depends on the request. Reported as [pixeltable#1688](https://github.com/pixeltable/pixeltable/issues/1688).
- **Code outside the project root stays cached in the pxt daemon.** `shared/` is imported by both backends, so a prompt or parser change there needs `pxt daemon restart` before `pxt schema update` or `pxt recompute`. `bench_evolve.py` counts it as a step.
- **The daemon refuses a file that changes its environment on import** (for example `load_dotenv()`), which is why `config.py` reads the environment only and `run_compare.sh` exports `.env` first.
- **`pxt` replaces a daemon that serves another project on its port**, so `run_compare.sh` gives this repo its own `PXT_PORT`.

## Limits

One machine, the median of a few rounds, one LLM on CPU. LLM output varies run to run, which is why the gates compare structure and transcripts, not wording. Nothing here says what happens at thousands of calls or with several workers.
