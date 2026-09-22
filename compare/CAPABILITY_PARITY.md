# Capability Parity — Pixeltable Platform vs Reference Stack

Canonical comparison doc for this monorepo. Product/API UI stories live in [FEATURE_PARITY.md](FEATURE_PARITY.md). Pipeline prompts and transforms live in [PIPELINE_SPEC.md](PIPELINE_SPEC.md). Code-level map: [BACKEND_MAPPING.md](BACKEND_MAPPING.md).

## How to read this doc

| Status | Meaning |
|--------|---------|
| **Equivalent** | Same user-visible behavior; implementation differs |
| **Partial** | Works but missing edge case or ops surface |
| **Gap** | Missing on one side |
| **Intentional diff** | Deliberate comparison datapoint — do not “fix” without updating this doc |
| **Platform advantage** | Pixeltable-native capability not replicated in Reference (documented, not a bug) |

**Verification:** `compare script` = automated gate; `manual` = spot check; `none` = not automated. Soft LLM theme checks in `compare_parity.py` are informational (do not fail the gate on wording variance).

---

## A. Product / API parity

| Feature | API | Reference | Pixeltable | Verify |
|---------|-----|-----------|------------|--------|
| Upload audio/video | `POST /api/calls/upload` | Equivalent | Equivalent | `compare_parity`, `smoke_test` (recommended; not in `compare_all` gates) |
| Upload size limit | same | Enforced | Enforced | manual |
| KPI banner | `GET /api/calls/kpis` | Equivalent | Equivalent | `compare_observability` |
| Call roster | `GET /api/calls` | Equivalent | Equivalent (`media_type` in list) | `compare_parity` |
| Filters | query params | Equivalent | Equivalent | manual |
| Hybrid search | `GET /api/search` | Completed calls only | Completed calls only | `compare_search` |
| Search lineage fields | enriched `SearchHit` | SQL JOIN | View lineage | `compare_search` |
| Call detail | `GET /api/calls/{id}` | Equivalent | Equivalent | `compare_parity` |
| Waveform audio | `GET /api/calls/{id}/audio` | Equivalent | Equivalent | `compare_parity` |
| Source video | `GET /api/calls/{id}/video` | Equivalent | Equivalent | `compare_parity` |
| Video–transcript sync | shared UI (`VideoPlayer`, `SyncTranscript`) | Segment `start_sec`/`end_sec` align with extracted-audio timeline (same as video t=0) | Same | manual |
| Coaching comments | `POST /api/comments` | `segment_id` optional | `call_uuid` + `segment_pos` (native) | `compare_mutations` |
| Delete call | `DELETE /api/calls/{id}` | Files + CASCADE | Comments deleted + row delete | `compare_mutations` |
| Flagged calls | `GET /api/calls/flagged` | Equivalent | Equivalent | `compare_observability` |
| Admin embed repair | `POST /api/admin/*` | When `ENABLE_ADMIN_ENDPOINTS` | N/A (declarative index) | none |
| Health | `GET /api/health` | postgres/redis/celery/ollama | catalog/ollama/pipeline | `compare_setup` |
| Embed ready | `GET /api/calls/{id}/embed-ready` | N/A | View materialization gate | seed / `pxt_api.wait_for_pixeltable_call` |

---

## B. Pipeline parity

See [PIPELINE_SPEC.md](PIPELINE_SPEC.md). Both backends implement the same WhisperX params, segment labeling, LLM prompts, empty-transcript **typed defaults**, and hybrid search contract.

**Empty-transcript intentional diff:** Reference skips all Ollama HTTP calls when transcript text is empty. Pixeltable uses native `ollama.chat` columns that still fire; `parse_*_content` returns the same typed defaults. Rare in fixtures; documented so compare does not treat it as a bug.

**Timing and serving tradeoffs** (not correctness bugs):

- Reference returns HTTP 202 on upload; Pixeltable returns HTTP 202 immediately (`{id, status: "queued"}`) and inserts the catalog row on a single-worker background executor. Both UIs poll call detail until `completed`.
- Pipeline speed benchmark uses API-visible `completed`. Pixeltable gates `completed` on segment view materialization (aligned with reference embed gating intent); seed/compare also poll `/embed-ready`.
- Pixeltable read APIs are **often** slower at small N due to catalog query engine + view iterator. Native `@pxt.query` + `FastAPIRouter` removes BFF mapping overhead but not structural read tax. Treat ratios as directional — see latest [`compare/reports/assess.json`](reports/assess.json).

---

## C. Pixeltable platform capabilities vs Reference

| Capability | What Pixeltable provides | Our Pixeltable usage | Reference equivalent | Status | Verify |
|------------|-------------------------|----------------------|----------------------|--------|--------|
| **Declarative pipeline** | Computed columns on insert | `schema.py` `TableModel` DAG | Celery `process_call.py` | Equivalent | `compare_parity` |
| **Incremental compute** | Recompute only changed columns | `recompute_columns()` via `scripts/demo_recompute.py` | Re-queue Celery task (reprocesses segments) | Partial | `demo_recompute` |
| **Media types** | `pxt.Audio`, `pxt.Video`, catalog storage | Yes + `extract_audio` | Filesystem + ffmpeg | Equivalent | `compare_parity` |
| **Views + lineage** | View inherits parent columns | `transcript_segments` view | SQL JOIN in search | Equivalent (API) | `compare_search` |
| **Embedding index** | `TableModel` `__indexes__` + `.similarity()` | Auto on view | pgvector HNSW + Celery embed | Equivalent search; ops differ | `compare_search` |
| **Keyword search** | `.contains()` | Yes | Postgres ILIKE | Equivalent | `compare_search` |
| **Versioning / snapshots** | `pxt.create_snapshot`, catalog history | Not used | Alembic migrations | Platform advantage | none |
| **Async upload** | Background insert | Manual `@router.post("/upload")` + serial `ThreadPoolExecutor` (multipart dual-file; not `add_insert_route`) | Celery 202-fast | **Equivalent** | `compare_speed`, `compare_concurrency` |
| **Observability** | Per-column `errormsg`, `pipeline_status` | Implemented | `Call.status` + `error_message` | Equivalent | `compare_observability` |
| **Recompute / repair** | `recompute_columns()` | `scripts/demo_recompute.py` (summary-only recompute) | Admin reembed/backfill + resume | Reference has dev repair | `demo_recompute` |
| **FastAPIRouter** | Declarative table routes | `@pxt.query` + `add_query_route` (list/flagged); custom upload/detail/media/delete | Hand-written FastAPI | **Platform advantage** | `compare_patterns` |
| **Concurrency** | Background executor, batch UDFs | ThreadPool upload + computed columns | Celery worker pool | Partial | `compare_concurrency` |
| **Embedding function** | Native `sentence_transformer.using(..., normalize_embeddings=True)` | Index on `transcript_segments` | `SentenceTransformer.encode` per segment | Equivalent output | `compare_search` |

---

## D. Reference strengths (fair comparison)

These are areas where Reference is **more complete** than Pixeltable in this repo:

| Area | Reference | Pixeltable gap |
|------|-----------|----------------|
| Delete cleanup | Removes upload files + CASCADE comments | Comments cascade added; catalog media handled by Pixeltable; temp upload dir files may remain |
| Explicit pipeline stages | Celery updates `embedding`, `diarizing` during run | Derived from column completion |
| Dev embed repair | Admin reembed/backfill endpoints | Declarative index (no repair API) |
| Read latency | Direct SQL ORM | Catalog + view iterator overhead |

---

## F. API contract (dual shapes, same UX)

| Aspect | Reference (`5173`) | Pixeltable (`5174`) |
|--------|-------------------|---------------------|
| List/detail field names | Shared Pydantic (`id`, `status`, `sentiment_label`) | Catalog-native (`uuid`, `pipeline_status`, `sentiment` JSON) |
| List response | `[{...}]` | `{"rows": [{...}]}` via `add_query_route` |
| Upload response | `{id, status}` | `{id, status: "queued"}`; catalog insert runs on background executor |
| Comments POST | `{call_id, segment_id?}` | `{call_uuid, segment_pos?}` |
| Compare normalization | n/a | `scripts/lib/pxt_api.py` + [pxt_api_mapping.json](pxt_api_mapping.json) |

Both UIs share React components; the Pixeltable dev server sets `VITE_BACKEND=pixeltable` and adapts in `client.pixeltable.ts`.

---

## G. Read vs write tradeoffs

| Dimension | Reference | Pixeltable |
|-----------|-----------|------------|
| Pipeline completion | Slower (serial LLM; embed before `completed`) | Faster (parallel LLM; declarative DAG) |
| Read API latency | Often faster (direct SQL ORM) | Often slower (catalog + view iterator); see `assess.json` |
| Serving code | Hand-written routers + shared schemas | `@pxt.query` + `FastAPIRouter` (no `mappers.py`) |
| Segment search storage | Normalized `transcript_segments` + pgvector | `list_iterator` view + embedding index |

Mapper removal was a serving cleanup, not the main read-latency story — structural catalog cost dominates. Ratios are reported honestly in `compare_assess.py`.

---

## H. Reference catch-up checklist (optional, for fairest benchmark)

These are **not implemented by default** — they close gaps where the vanilla stack is slower or less capable, without matching Pixeltable platform features.

| Gap | Reference change | Effort | Closes |
|-----|------------------|--------|--------|
| Serial LLM enrichment | Parallel `asyncio.gather` in `ollama_client.enrich_call` | Small | ~10–15 s on billing fixture |
| Embed after enrich only | Start `embed_call_segments` after segment persist, parallel with Ollama | Medium | 1–3 s+ overlap |
| `completed` semantics | Already gates on embed; Pixeltable aligned via view row gate | Small | Fair speed benchmark |
| Incremental recompute | Optional task to re-enrich only changed fields | Large | Ops parity (not speed) |
| Stage timers | Per-status timestamps in DB + `compare_speed` breakdown | Small | Evidence in reports |
| Versioning / snapshots | Alembic only | N/A | Document as Pixeltable platform advantage |
| FastAPIRouter / job polling | N/A by design | N/A | Showcase narrative for Pixeltable |

---

## I. Cost to replicate in vanilla

What Pixeltable provides **for free** in this app, what the Reference stack already builds by hand, and how far §H catch-up goes. This is the value-add story for the comparison — not a claim that Reference is incomplete as a product.

| Pixeltable “for free” | Vanilla equivalent in this repo | Catch-up path (§H) |
|----------------------|----------------------------------|--------------------|
| Computed-column DAG on insert | `process_call.py` + status commits | N/A (architecture) |
| Parallel enrichment columns | Serial `OllamaClient.enrich_call` | `asyncio.gather` |
| `add_embedding_index` + `.similarity()` | Alembic pgvector + embed tasks + admin repair | Already partial |
| `recompute_columns` (leave transcription intact) | Full Celery re-queue (can orphan comment anchors) | Incremental re-enrich task |
| `extract_audio` / `whisperx.transcribe` built-ins | `video.py` + `whisperx_service.py` | Already exists |
| `@pxt.query` + `add_query_route` | Hand-written routers + Pydantic | N/A by design |
| No Redis / Celery / Alembic for the Pixeltable path | `docker-compose` + worker + migrations | Ops burden, not a product feature gap |
| Per-column `errormsg` | Single `call.error_message` | Optional richer errors |

**Honest bias today:** Pixeltable tends to win **pipeline wall-clock** (parallel LLM DAG). Reference tends to win **read latency** and **explicit ops tooling** (admin repair, filesystem delete). Product/API parity is what the compare gates enforce.

---

## E. Changelog

| Date | Change |
|------|--------|
| 2026-07-09 | Pixeltable enrichment: native `ollama.chat` `*_raw` columns + `vertical_prompt`; removed httpx `enrichment_chat`. Empty-transcript Ollama calls accepted (parsers still default). |
| 2026-07-08 | Docs hygiene: native serving paths, cost-to-replicate §I, async upload / FastAPIRouter accuracy, soften read-latency claim, embed-ready documented. |
| 2026-07-07 | Native Pixeltable serving: `@pxt.query`, `FastAPIRouter`, `pxt.Json` enrichment, background upload jobs; removed `mappers.py`; dual API contract + compare normalization; CAPABILITY_PARITY sections F–H. |
| 2026-07-06 | Shared segmentation module; empty-transcript enrichment skip; stronger parity gates; incremental recompute demo; admin resume endpoint; embed failure surfacing; API-safe audio_path. |
| 2026-07-03 | Initial capability matrix. Fixed Pixeltable list `media_type`, delete comments cascade, search completed filter, status machine, comment `segment_pos=-1`. Reference upload size + webm alignment. UI error states + seek URL sync. |

---

## Running verification

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full compare workflow and script reference.

```bash
./scripts/run_compare.sh seed
uv run python scripts/compare_all.py --full
uv run python scripts/compare_assess.py
uv run python scripts/smoke_test.py --backend both   # recommended; not a compare_all gate
uv run python scripts/demo_recompute.py
```
