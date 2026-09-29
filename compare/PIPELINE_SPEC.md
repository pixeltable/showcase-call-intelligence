# Pipeline specification

Both backends implement this contract. The gates in `scripts/compare_parity.py` and `scripts/compare_mutations.py` compare API responses, not storage.

## Fixtures

Ten recordings in [`fixtures/manifest.json`](fixtures/manifest.json), five audio and five video, covering the four verticals. Committed WAVs are synthetic or extracted; videos are fetched by [`scripts/fetch_fixtures.py`](../scripts/fetch_fixtures.py) and derived by [`scripts/prepare_fixture_media.py`](../scripts/prepare_fixture_media.py). Attribution: [`fixtures/ATTRIBUTION.md`](fixtures/ATTRIBUTION.md). The seed shifts the manifest's dates so the newest call lands one hour before the seed runs, which keeps every seeded call inside the 7-day KPI window.

| Vertical | Audio | Video |
|---|---|---|
| call_center | billing-inquiry-speech, cancellation-request | pursuit-happiness-video |
| sales | sales-discovery | sales-demo-video (copy) |
| podcast | podcast-excerpt-audio (extract) | lex-fridman-excerpt, travel-briefing |
| interview | interview-behavioral | interview-session (copy) |

## Models (identical on both)

| Variable | Default | Used for |
|---|---|---|
| `WHISPERX_MODEL` | `base` | ASR, CPU, `int8`, batch 16 |
| `WHISPERX_DIARIZATION_MODEL` | `pyannote/speaker-diarization-3.1` | diarization, `num_speakers=2` (needs `HF_TOKEN`) |
| `OLLAMA_MODEL` | `llama3.1` | the five enrichments, through one Ollama server |
| `EMBED_MODEL` | `all-mpnet-base-v2` | 768-dim segment embeddings, normalized |

The Reference's [`whisperx_service.py`](../backends/reference/app/services/whisperx_service.py) runs the same steps as Pixeltable's `whisperx.transcribe` UDF: load, transcribe, align, diarize, assign speakers.

## Ingest

- Audio: `.wav .mp3 .m4a .ogg .flac .webm`. Video: `.mp4 .mov .mkv`. Anything else is a 400. Uploads over `MAX_UPLOAD_MB` are a 400.
- `POST /api/calls/upload` returns `202 {id, status}` before any processing.
- Video: extract MP3 audio (Pixeltable: the `extracted_audio` computed column; Reference: ffmpeg in the Celery task), then transcribe it.

## Segments and transcript

From WhisperX `segments`: the first distinct speaker is `AGENT`, the second `CUSTOMER`; with one speaker, a regex on greeting and complaint phrases decides, else the index alternates. Empty segments are dropped. Shared code: [`segmentation.py`](../shared/call_center_api/segmentation.py). The LLM sees one line per segment:

```
[{start:.1f}s-{end:.1f}s] {SPEAKER}: {text}
```

## Enrichment

Five Ollama chat calls per call, system prompt from `get_profile(vertical).prompts` ([`verticals.py`](../shared/call_center_api/verticals.py)), parsed by [`enrichment.py`](../shared/call_center_api/enrichment.py). Both backends make the five calls one after another: the Reference loops in `OllamaClient.enrich_call`; Pixeltable's `ollama.chat` is a synchronous UDF, and its engine runs synchronous UDFs one at a time.

| Field | JSON mode | Output |
|---|---|---|
| summary | yes | `{"bullets": [...]}`, stored as newline-joined lines |
| action_items | yes | array of strings |
| sentiment | yes | `{label, score, rationale, moments[]}`; a moment is `{start_sec, end_sec?, polarity, reason}` |
| category | no | one label |
| qa_scorecard | yes | `{empathy, resolution, compliance, overall, notes}`, scores clamped to 0-10 |

**No speech:** neither backend calls the LLM. The Reference checks the transcript in Python. On Pixeltable the transcript is null, and a null argument to a non-nullable UDF parameter skips the call, so all five cells skip. Both store the same defaults:

| Field | Value |
|---|---|
| summary | `""` |
| action_items | `[]` |
| sentiment | `{"label": "unknown", "score": 0.5, "rationale": "", "moments": []}` |
| category | `"Uncategorized"` |
| qa_scorecard | zeros, `notes: ""` |
| handle_time_sec | `0.0` |

## Status

| Backend | What a client sees while a call is processed |
|---|---|
| Reference | `queued`, `transcribing`, `diarizing`, `enriching`, `embedding`, then `completed` or `failed`. The Celery task commits each stage, and the roster lists the call from the start. |
| Pixeltable | `processing`, then `completed` or `failed`. A row commits only when every computed column, its segment rows and their embeddings are done, so there is no stage to report and the roster lists the call once it is done. The detail route answers `processing` from the upload it accepted. |

`failed` on Pixeltable means a cell holds an error (`errormsg`); a failed cell also fails every column computed from it, and the other cells keep their values. On the Reference, `failed` means the task raised; stages already committed stay.

## Embeddings and search

One vector per segment. Reference: `SentenceTransformer.encode` into a `vector(768)` column with an HNSW index, and the query is embedded by hand. Pixeltable: `EmbeddingIndex(text, embedding=sentence_transformer.using(...))` on the `transcript_segments` view, maintained on insert and delete; `similarity(string=q)` embeds the query with the same model.

`GET /api/search?q&mode=keyword|semantic|hybrid&limit`: keyword hits (case-insensitive substring, newest first, `score` 1.0) then semantic hits not already returned (`score` is cosine similarity), from calls that completed without errors.

## Media

`GET /api/calls/{id}/audio` streams the audio that was transcribed (the extracted MP3 for a video). `GET /api/calls/{id}/video` streams the original video.

## Comments and delete

`POST /api/comments {call_id, segment_id?, start_sec, author, comment}`: 404 for an unknown call, 400 (Pixeltable) or 422 (Reference, whose ids are UUIDs) for a segment of another call. Segment ids are opaque strings: database UUIDs on the Reference, `{call_id}:{pos}` on Pixeltable.

`DELETE /api/calls/{id}` removes the call, its segments and their embeddings, its comments, and its upload files; a second delete is a 404. `compare_mutations.py` checks each store directly.
