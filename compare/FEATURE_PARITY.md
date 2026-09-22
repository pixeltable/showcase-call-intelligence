# Feature Parity — UI User Stories vs Backends

Shared UI: [`frontend/`](../frontend/). Compare tabs: Reference `:5173` → `:8001`, Pixeltable `:5174` → `:8000`.

**Full capability matrix:** see [CAPABILITY_PARITY.md](CAPABILITY_PARITY.md) (platform features, pipeline ops, intentional diffs).

| User story | UI component | API | Reference | Pixeltable |
|------------|--------------|-----|-----------|------------|
| Upload audio or video | `UploadForm` | `POST /api/calls/upload` (+ optional `vertical`) | OK | OK |
| KPI banner | `KpiBanner` | `GET /api/calls/kpis` | OK | OK |
| Call roster + poll | `CallRoster` | `GET /api/calls` | OK | OK |
| Sentiment/queue filter | `Dashboard` | `GET /api/calls?...` | OK | OK |
| Global search + seek | `GlobalSearch` | `GET /api/search` | OK | OK |
| Call detail | `CallWorkspace` | `GET /api/calls/{id}` | OK | OK |
| Waveform playback | `WaveformPlayer` (play/pause + segment clip on audio-only; muted sync on video) | `GET /api/calls/{id}/audio` | OK | OK |
| Video + transcript sync | `VideoPlayer` + `SyncTranscript` | `GET /api/calls/{id}/video` + segment timestamps | OK | OK |
| Sync transcript (audio) | `SyncTranscript` | segments in detail | OK | OK |
| Sentiment moments | `CallWorkspace` | `sentiment.moments[]` (+ legacy `flags`) | OK | OK |
| Intelligence sidebar | `IntelligenceSidebar` | summary, action_items, qa | OK | OK |
| Coaching comments | `CoachingComments` | `POST /api/comments` | OK | OK |
| Processing / failed | roster + workspace | status, error_message | OK | OK |
| Delete call | — | `DELETE /api/calls/{id}` | OK | OK |
| Flagged calls | — | `GET /api/calls/flagged` | OK | OK |

LLM-generated text (summary, QA scores) may differ run-to-run; structural parity is what matters.

## Segment model

Both backends store **diarized speech segments** (utterance-level turns), not arbitrary RAG text chunks. Transform semantics are defined in [`PIPELINE_SPEC.md`](PIPELINE_SPEC.md).

- **Reference:** WhisperX + pyannote → Postgres `transcript_segments` rows → Sentence Transformers embed per segment (pgvector).
- **Pixeltable:** WhisperX diarization → `segments` computed column → `transcript_segments` view via `list_iterator` → embedding index.

Search parity is at segment granularity on both sides. Search returns **completed calls only** on both backends.

## Shared API contract

Reference serves the Pydantic models in [`shared/call_center_api/schemas.py`](../shared/call_center_api/schemas.py). Pixeltable serves catalog-native JSON (`uuid`, `pipeline_status`, nested `sentiment`); the Pixeltable UI adapts in [`frontend/src/api/client.pixeltable.ts`](../frontend/src/api/client.pixeltable.ts) (`VITE_BACKEND=pixeltable`). Compare scripts normalize via [`scripts/lib/pxt_api.py`](../scripts/lib/pxt_api.py). See [CAPABILITY_PARITY.md §F](CAPABILITY_PARITY.md).

`CallSummary` / `CallDetail` include `vertical` (default `call_center`). Upload form metadata slots (`agent_id`, `customer_id`, `queue`) are relabeled in the UI per vertical via [`frontend/src/lib/verticals.ts`](../frontend/src/lib/verticals.ts).

## Reference upload fix

Reference uploads use a **single call UUID** for the DB row and filenames, and store **absolute paths** under `data/reference/uploads/`. Seed reset (`scripts/seed_compare.py`) truncates Postgres and clears that upload directory.

## Intentional comparison differences

Documented in [CAPABILITY_PARITY.md](CAPABILITY_PARITY.md) and [CONTRIBUTING.md](../CONTRIBUTING.md):

- Pixeltable read APIs are often slower at small N (catalog + view iterator); see latest `compare/reports/assess.json`
- Reference admin embed repair endpoints (dev only)
- Dual wire shapes (Reference Pydantic vs Pixeltable catalog-native) with the same React components
