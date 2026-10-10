# Capability parity

Both backends serve one contract ([`shared/call_center_api/schemas.py`](../shared/call_center_api/schemas.py)) to one React client ([`frontend/src/api/client.ts`](../frontend/src/api/client.ts)). This page lists what the gates hold equal, and every place the two still differ on the wire or in behavior. What each side gets from its platform is in [WHY_PIXELTABLE.md](WHY_PIXELTABLE.md).

## Held equal by the gates

| User story | Route | Gate |
|---|---|---|
| Upload audio or video, choose a vertical | `POST /api/calls/upload` | `compare_mutations`, `benchmark` |
| Roster, filters by agent, queue, sentiment, handle time | `GET /api/calls` | `compare_parity` |
| KPI banner (7 days) | `GET /api/calls/kpis` | `compare_parity` |
| Flagged calls | `GET /api/calls/flagged` | `compare_parity` |
| Call detail: transcript, speakers, summary, action items, sentiment moments, category, QA | `GET /api/calls/{id}` | `compare_parity` (transcript word agreement at least 0.9, same speakers, segment count within 1) |
| Waveform audio, source video | `GET /api/calls/{id}/audio`, `/video` | `compare_parity` |
| Keyword, semantic and hybrid search, seek to the hit | `GET /api/search` | `compare_parity` |
| Coaching comments, anchored or call-level | `POST /api/comments`, `GET /api/comments/call/{id}` | `compare_mutations` |
| Delete a call with everything it owns | `DELETE /api/calls/{id}` | `compare_mutations`, down to each store |
| Dependency health | `GET /api/health` | `compare_parity` |

LLM wording is not compared: it is the model's, not the backend's.

## Where they still differ

| Difference | Reference | Pixeltable | Why |
|---|---|---|---|
| List envelope | `[...]` | `{"rows": [...]}` | the current roster handler retains the original envelope; the client accepts both (`requestRows`) |
| Progress while processing | a stage per commit | `processing` from a persisted receipt; the roster includes accepted uncommitted calls | a Pixeltable row commits with all its computed columns |
| Segment ids | database UUIDs | UUIDv5 of the call id and the segment's position | segments are rows of an iterator view keyed by position |
| A failed step | the call is `failed`; stages already committed stay | the failing cell and the cells computed from it hold the error; the others keep their values | per-cell errors |
| Deleting a call that is still processing | immediate | 409 until its receipt reaches a terminal state | prevents deletion from racing a scheduled insert |
| A restart while a call is processing | the `queued` row and its last status stay | media and receipt survive; startup reconciles an existing call or resumes its pending insert | local single-writer receipt recovery; failed work does not retry automatically |
| Upload retry keys / capacity | no idempotency contract or bounded admission in this app | `Idempotency-Key` deduplicates normalized metadata + bytes; changed input409, deleted key410, full pending queue429 | deliberately different intake boundary; historical runtime measurements predate it |
| Search readiness | detail defaults to unknown | persisted last-insert diagnostics; legacy/reconciled calls unknown | additive shared detail fields; not a continuous index audit |
| Admin repair routes (`/api/admin/*`) | behind `ENABLE_ADMIN_ENDPOINTS` | none; `pxt errors` and `pxt recompute` from the CLI | repair is a platform command |

## Shared by construction

Prompts, response parsers, speaker labeling, the segment transcript format and the upload rules live in [`shared/call_center_api`](../shared/call_center_api) and are imported by both. Model identifiers and intended logical parameters are shared ([PIPELINE_SPEC.md](PIPELINE_SPEC.md)); execution-device and index-precision differences are explicit [methodology limits](METHODOLOGY.md#what-is-compared).
