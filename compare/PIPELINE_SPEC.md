# Pipeline specification (both backends)

Both backends implement this contract independently. Parity tests compare API JSON, not internal storage.

Compare fixtures (10 entries: 6 audio + 4 video) are defined in [`fixtures/manifest.json`](fixtures/manifest.json). Each vertical (`call_center`, `sales`, `podcast`, `interview`) has at least one audio and one video fixture. Video files are fetched via [`scripts/fetch_fixtures.py`](../scripts/fetch_fixtures.py); derived copies/extracts via [`scripts/prepare_fixture_media.py`](../scripts/prepare_fixture_media.py); synthetic WAVs via [`scripts/generate_fixture_audio.py`](../scripts/generate_fixture_audio.py). See [`fixtures/ATTRIBUTION.md`](fixtures/ATTRIBUTION.md).

| Vertical | Audio fixtures | Video fixtures |
|----------|----------------|----------------|
| call_center | billing-inquiry, cancellation-request | pursuit-happiness |
| sales | sales-discovery | sales-demo (copy) |
| podcast | podcast-excerpt (extract) | lex-fridman, travel-briefing |
| interview | interview-behavioral | interview-session (copy) |

## Environment

| Variable | Default | Used by |
|----------|---------|---------|
| `WHISPERX_MODEL` | `base` | WhisperX ASR |
| `WHISPERX_DIARIZATION_MODEL` | `pyannote/speaker-diarization-3.1` | WhisperX diarization |
| `HF_TOKEN` | (required for diarization) | Hugging Face / pyannote |
| `OLLAMA_MODEL` | `llama3.1` | Enrichment chat (Ollama) |
| `EMBED_MODEL` | `all-mpnet-base-v2` | Segment embeddings (Hugging Face Sentence Transformers) |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama client (chat only) |

WhisperX transcribe parameters (both backends):

- `diarize=True`
- `num_speakers=2`
- `diarization_model_name=$WHISPERX_DIARIZATION_MODEL`

## Ingest

- Accept audio (`.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.webm`) and video (`.mp4`, `.mov`, `.mkv`).
- **Audio path:** store uploaded audio; transcribe directly.
- **Video path:** extract audio as **MP3** (Pixeltable: `extract_audio(video, format="mp3")`; reference: ffmpeg equivalent), then transcribe extracted audio.

## Transcribe

One WhisperX call per call on `audio ?? extracted_audio`.

## Segment extraction

From WhisperX `diarized["segments"]`:

1. Build speaker map: first distinct raw speaker → `AGENT`, second → `CUSTOMER`.
2. If only one raw speaker: infer from regex (`AGENT` greeting patterns, `CUSTOMER` speech patterns), else alternate by index.
3. Drop segments with empty text.
4. Output rows: `{speaker, start_sec, end_sec, text}` with `speaker` in `{AGENT, CUSTOMER}`.

## LLM transcript format

```
[{start:.1f}s-{end:.1f}s] {SPEAKER}: {text}
```

One line per segment, joined with `\n`.

## LLM prompts (system messages)

Canonical prompt text and response parsers live in [`shared/call_center_api/enrichment.py`](../shared/call_center_api/enrichment.py) and [`shared/call_center_api/verticals.py`](../shared/call_center_api/verticals.py). Both backends import from those modules.

Upload accepts optional `vertical` (`call_center` | `sales` | `podcast` | `interview`; default `call_center`). Enrichment system prompts are selected via `get_profile(vertical).prompts`; output JSON shapes and parsers are unchanged across verticals.

| Field | JSON mode | Output shape |
|-------|-----------|--------------|
| Summary | yes | `{"bullets": ["...", ...]}` → stored as newline-joined plain strings |
| Action items | yes | JSON array of strings (agent commitments, follow-ups) |
| Sentiment | yes | `{label, score, rationale, moments[]}` — each moment: `{start_sec, end_sec?, polarity, reason}` |
| Category | no | Single category label string |
| QA scorecard | yes | `{empathy, resolution, compliance, overall, notes}` |

Post-processing (shared parsers): extract JSON from fenced/prose wrappers, strip markdown preambles from summaries, clamp QA scores to 0–10, validate sentiment labels, normalize `moments` with polarity (`positive|neutral|negative`). Legacy `flags` arrays are read as negative moments for backward compatibility.

### Sentiment moments (waveform)

- **Call-level:** `label`, `score`, `rationale` — overall QA assessment.
- **Time-aligned:** `moments[]` with `polarity`, `start_sec`, optional `end_sec`, and `reason`.
- **UI:** waveform regions color-coded (negative=red, neutral=amber, positive=green); sidebar lists all moments.
- **Flagged calls API:** still driven by negative label, low score, or negative-polarity moments (not positive highlights).

## Empty transcript

When transcript text is empty after segment extraction, both backends expose the same **typed defaults**:

| Field | Value |
|-------|-------|
| `summary` | `""` |
| `action_items` | `[]` |
| `sentiment` | `{"label":"unknown","score":0.5,"rationale":"","moments":[]}` |
| `category` | `"Uncategorized"` |
| `qa_scorecard` | `{"empathy":0,"resolution":0,"compliance":0,"overall":0,"notes":""}` |
| `handle_time_sec` | `0.0` |

**How they get there (intentional diff):**

- **Reference:** skips all Ollama HTTP calls and writes defaults directly.
- **Pixeltable:** native `ollama.chat` columns still fire; `parse_*_content` returns the defaults above when transcript is empty.

## Status machine

API `status` values: `queued` → `transcribing` → `diarizing` → `enriching` → `embedding` → `completed` (or `failed` on error).

- **Reference:** Celery task updates `Call.status` through each stage.
- **Pixeltable:** `pipeline_status` computed column derived from column completion.
- **Zero segments is OK:** pipeline completes after enrichment defaults; status must reach `completed`.

## Embeddings

- Model: `all-mpnet-base-v2` (Hugging Face Sentence Transformers, 768-dim)
- One vector per segment `text`
- Ollama is used for **chat/enrichment only**, not embeddings

| Backend | Implementation | Semantic query |
|---------|----------------|----------------|
| **Reference** | `SentenceTransformer.encode()` in [`embed_service.py`](../backends/reference/app/services/embed_service.py) → pgvector HNSW | SQL `cosine_distance` |
| **Pixeltable** | Native `sentence_transformer.using(model_id=EMBED_MODEL, normalize_embeddings=True)` on `transcript_segments` embedding index | `segments.text.similarity(string=query)` |

Reference does **not** use Pixeltable. Pixeltable enrichment uses built-in `pixeltable.functions.ollama.chat` as five independent `*_raw` computed columns on the `Calls` `TableModel` in [`schema.py`](../backends/pixeltable/schema.py) (Pixeltable 0.7.8 class-based schema), with system prompts from `functions.vertical_prompt` and typed columns via `parse_*_content` UDFs. Accessor: `chat(...)['message']['content']`.

### Pixeltable provider rules

**Ollama (chat / enrichment)** — use `ollama.chat` as top-level computed columns only (never inside a custom `@pxt.udf`). Vertical prompts come from `vertical_prompt(vertical, field)`. Empty transcripts still invoke `chat` (no expression short-circuit); parsers return typed defaults. Reference skips HTTP on empty transcript — intentional diff.

**Hugging Face embeddings** — use `sentence_transformer.using(model_id=..., normalize_embeddings=True)` on the `TableModel` embedding index. Default `normalize_embeddings` is `False`; both backends normalize so `score` stays comparable. Pin `sentence-transformers>=5.4,<6` (ST 6 wants `huggingface-hub>=1.3`; WhisperX 3.8.6 wants `<1.0`). ST 5.4 guards torchcodec import; a torchcodec vs ffmpeg 8 (`libavutil.60`) mismatch can still break **pyannote/WhisperX** — confirm `diarized` materializes before blaming Ollama.

Custom UDFs in [`functions.py`](../backends/pixeltable/functions.py) also parse/transform (e.g. `parse_summary_content`) and derive `pipeline_status`.

### Embed readiness (Pixeltable)

Seed and compare wait helpers poll `GET /api/calls/{uuid}/embed-ready` until the `transcript_segments` view has materialized rows for the call (aligned with Reference gating `completed` on embed). Implemented in [`routers/native.py`](../backends/pixeltable/routers/native.py); used by [`scripts/lib/pxt_api.py`](../scripts/lib/pxt_api.py).

### Index maintenance

| Event | Pixeltable | Reference |
|-------|------------|-----------|
| New segments | Embedding index auto-computes on view materialization | `embed_segments()` in Celery `process_call` |
| Failed embed | Index skips until column value exists | Sets `embedding = NULL`; triggers `reembed_call` task |
| Call delete | Index entries pruned with parent row | `ON DELETE CASCADE` on segments; HNSW index follows row deletes |
| Backfill | N/A (declarative) | Celery `backfill_embeddings` task; dev admin `POST /api/admin/backfill-embeddings` when `ENABLE_ADMIN_ENDPOINTS=true` |

Reference dev repair: `POST /api/admin/reembed/{call_id}` re-queues embedding for segments with NULL vectors.

## Search API

`GET /api/search` returns enriched `SearchHit` objects:

- `segment_pos` — utterance index (lineage key)
- `match_type` — `keyword` or `semantic`
- `media_type` — `audio` or `video` (from parent call)
- `original_filename` — source upload name
- `vertical` — use case profile (`call_center`, `sales`, `podcast`, `interview`; default `call_center`)

Pixeltable resolves parent call fields via view lineage (no JOIN). Reference resolves via SQL JOIN.

Media endpoints:

- `GET /api/calls/{id}/audio` — transcribe/playable audio (extracted MP3 for video calls)
- `GET /api/calls/{id}/video` — original video file when `media_type=video`

## Retrieval

HTTP responses use [`shared/call_center_api/schemas.py`](../shared/call_center_api/schemas.py). Segment `speaker` values are `AGENT` / `CUSTOMER` in API output.

## Mutation lifecycle

Detail-page mutations (coaching comments, call delete) are verified by `scripts/compare_mutations.py`. Tests use **ephemeral uploads** so seeded fixture IDs in `.compare-state.json` stay intact.

### Coaching comment create (`POST /api/comments`)

| Concern | Pixeltable | Reference |
|---------|------------|-----------|
| Storage | Insert into `coaching_comments` table | Insert into `coaching_comments` row |
| Segment anchor | Resolve `segment_id` → `segment_pos` (`backends/pixeltable/routers/comments.py`) | FK `segment_id` optional (`backends/reference/app/routers/comments.py`) |
| Search / embeddings | **No change** (comments not indexed) | **No change** |
| Lineage | Standalone table keyed by `call_uuid` | FK to `calls` + optional `transcript_segments` |

### Call delete (`DELETE /api/calls/{id}`)

| Dependency | Pixeltable (declarative) | Reference (explicit) |
|------------|------------------------|----------------------|
| Coaching comments | `comments.delete(call_uuid=…)` then `calls.delete` | SQLAlchemy `cascade="all, delete-orphan"` on `Call.comments` |
| Transcript segments | View `transcript_segments` rows removed when parent call deleted | `ON DELETE CASCADE` on `TranscriptSegment.call_id` |
| Embedding index | Index on view auto-prunes with segment rows | pgvector HNSW follows row deletes — no separate reindex task |
| Upload media | Catalog/blob lifecycle via Pixeltable storage | `delete_upload_files()` before ORM delete |
| Search / KPIs / roster | Deleted call absent from catalog queries | Deleted rows absent from SQL; no cache invalidation |
| Celery / pipeline | N/A (no worker) | N/A on delete (no task to cancel) |

Reference does **not** need `reembed_call` / `backfill_embeddings` on delete — only on failed embed during ingest.
