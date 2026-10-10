# Call-intelligence showcase review

Reviewed October 8–9, 2026, on the existing `measured-comparison` branch. The initial checkout was clean. The review upgrades the Pixeltable backend, fixes defects in both implementations, improves the shared UI, and makes the developer and researcher paths easier to assess. The subsequent first-lesson pass builds on commit `bf77374`. The comparison structure and original runtime evidence are preserved. No existing call catalog was reset.

## Assessment

The Pixeltable implementation demonstrates the intended foundation for a coding agent: a `TableModel` schema, a computed-column dependency graph, typed segment expansion, an embedding index, and a `FastAPIRouter` in one application module. Product rules stay in the shared package. Imports do not create or mutate catalog objects, models load through provider wrappers rather than once per row, and application queries use the public SDK.

This is a credible local developer showcase after the fixes below. It is not yet a fully validated production intake service or a model-quality benchmark. The October 10 release closes local durable acceptance with a single-writer receipt spool and persists last-insert search diagnostics. Public deployment, continuous index-readiness verification, and real-model completion remain separate boundaries. The README now states those boundaries next to the narrative instead of implying that a compact backend alone settles deployment readiness.

## Findings and changes

| Priority | Evidence and impact | Change |
|---|---|---|
| P1 | [`shared/call_center_api/enrichment.py`](../shared/call_center_api/enrichment.py): invalid JSON, wrong object shapes, missing scores, and non-finite numbers were converted to empty lists, unknown sentiment, or zero scores. Both backends reported success, preventing meaningful error recovery. | Required JSON shapes, string arrays, summary bullets, and finite numeric scores now validate and raise. Empty model responses fail when a transcript exists. Real no-speech defaults still bypass model calls. Summary Markdown/plain-text compatibility is retained. |
| P1 | [`backends/pixeltable/app.py`](../backends/pixeltable/app.py): call status omitted input media and intermediate transform errors. | The status/error filter covers audio, video, extraction, source audio, ASR, segments, transcript, handle time, and all enrichment cells. Hand-written responses also validate against the shared models. |
| P1 | Both media APIs served an extracted MP3 with the original video's filename and inferred video MIME type. | Download filenames use the served file's extension. The generated-video integration test verifies video extraction and audio/video response types; the Reference contract test verifies the same filename behavior. |
| P1 | The Pixeltable KPI endpoint indexed the first aggregate result even when an empty catalog returned no rows. A real service startup reproduced HTTP 500. | Empty catalogs now return a valid zero-count response, with an integration regression test and a live HTTP verification. |
| P1 | Semantic query failures could become an empty success on the Reference; missing Pixeltable vectors could appear as unscored semantic hits. | Semantic query/provider failures return 503 with a keyword-mode recovery instruction. Missing vectors are excluded. Pixeltable insert results log all failed-column diagnostics. Hidden index failure state remains a separate readiness limitation below. |
| P1 | [`scripts/lib/client.py`](../scripts/lib/client.py): failed Ollama unload/load HTTP requests and an unload timeout did not stop a benchmark. | Every reset request checks status; timeout stops measurement. Model tags are matched exactly. Mocked failure tests protect the protocol. |
| P1 | README claimed accepted Reference work survives a restart, beyond the implemented guarantee. The database commit and Celery publish are separate; Redis has no persistence, and tasks use early acknowledgement. | Claims now distinguish durable call records from automatic task recovery. No untested durability mechanism was added. |
| P2 | Query bounds, blank searches, naive timestamps, and comment timestamps had inconsistent validation. | Positive bounded limits, nonblank search input, bounded upload metadata, timezone-aware call dates, finite nonnegative comment times, and bounded comments now return explicit validation errors. |
| P2 | The Reference flagged-call handler examined only an arbitrary first page before filtering. | It iterates the ordered completed calls until it finds the requested number of flagged calls. A regression test puts the matching call beyond the old prefix. |
| P2 | Health checks accepted a different tag of the configured Ollama model. | Both backends require the exact configured tag, with `:latest` used when no tag is given. These remain connectivity/configuration checks, not proof that every model is loaded. |
| P2 | Benchmark sections could be merged from different dirty source states at one commit; an ordinary warm-up was labeled a cold start. | Each invocation now records its source fingerprint and only its own measurements. Warm-up wording is corrected in the renderer and documentation; historical timing values remain unchanged. |
| P2 | Compose published demo database, Redis, and Ollama ports on every host interface. | These ports bind to localhost. |
| P2 | UI loading failures could look like genuine zero KPIs; navigation and form labels were incomplete; waveform failure left ambiguous playback controls. | The shared UI now has explicit loading/error/retry states, labeled controls, accessible recording navigation, media failure handling, reduced-motion behavior, and a responsive roster. Transient upload polling failures preserve the pending upload. |

## Upgrade and migration behavior

[`backends/pixeltable/pyproject.toml`](../backends/pixeltable/pyproject.toml) now requires `pixeltable[serve]>=0.7.16,<0.8`, and its regenerated lock resolves 0.7.16. The release was verified on October 9 against [PyPI](https://pypi.org/project/pixeltable/0.7.16/) and the installed package. The upgrade adds the SDK's boto3 dependencies; the existing ASR and embedding dependencies were not deliberately upgraded.

Schema and service checks used the installed 0.7.15 implementation, not only syntax parsing. The production declarations created successfully in a temporary catalog. After the application changes, `pxt schema diff` showed all three objects unchanged and no destructive operations. An isolated `pxt service update` started the real HTTP service, whose empty list, flagged list, KPI, input-validation, and OpenAPI routes were checked. Only review-owned services and catalogs were used.

Existing users should install the frozen lock, export the configured environment before starting Pixeltable, restart the daemon when shared Python transforms change, review the schema diff, apply the schema, and update the service. Existing malformed/defaulted enrichment values are not automatically repaired by changing a parser: inspect the affected rows and explicitly recompute the intended columns. Recomputing model-backed fields invokes those models again.

## First lesson and research follow-through

The first-lesson pass introduced one Pixeltable backend and UI, with Ollama as its only Docker service. It uses a dedicated `data/lesson/` catalog and one committed six-second audio fixture. Repeated seeding reuses the saved call rather than resetting stores or uploading a duplicate. The full comparison remains optional and always selects the original full enrichment profile.

The core profile requests only the summary model call; category, action items, sentiment, and QA remain null. Health, roster, and detail responses identify the profile, and the core sentiment KPI is null. This removes actual optional provider work and avoids presenting omitted assessments as scores. The UI leads with summary/evidence, keeps demo metadata editable under a disclosure, and demotes uncalibrated optional assessments. Core and full declare different column kinds; their launchers use separate catalogs rather than attempting an in-place profile migration.

[`examples/extend_call.py`](../examples/extend_call.py) adds a small business-rule column to stored transcript data, changes its expression without immediate recomputation, then recomputes that field explicitly. It checks that transcript, summary, segments, and a probe comment anchor are preserved, and removes its own temporary field/comment afterwards. The CLI is confined to the lesson home. The integration tests execute the same helper on isolated production tables and confirm zero additional ASR, chat, or embedding calls.

A further research defect was identified in `bench_evolve.py`: partial or failed invocations could retain old successful sections while replacing their global timestamp/model. Each invocation now reserves a unique report under `compare/reports/evolve/`, captures source/environment/model/fixture/patch provenance, and records status/timestamps per attempted experiment. Failure and interruption carry explicit errors; existing output paths are refused before setup or experiment work. Historical `compare/results/evolve.json` is never loaded, merged, or overwritten by the harness. Promotion to published results remains a deliberate review step.

## Verified in this pass

The original focused run passed 97 test executions across the suites/profiles below; the full-profile run skips the core-only case intentionally. Both FastAPI test suites emit the installed Starlette adapter's `httpx` deprecation warning. The review-owned service and daemon were stopped after the original live checks.

| Check | Result and boundary |
|---|---|
| Shared transforms, model-response validation, fixture metadata, and vertical profiles | 47 tests passed. Pure Python checks; no external providers. |
| Pixeltable integration | 17 full-profile tests and 2 core-profile tests passed using temporary real catalogs, tables, computed columns, iterator views, vector indexes, and FastAPI routes. ASR, LLM, and embeddings were deterministic substitutes. The full run intentionally skips the core-only case. |
| Media processing | The integration suite generated a real audio/video container and executed Pixeltable's built-in MP3 extraction. It verified playback response types, comments, current-row deletion, view/index cascades, and upload cleanup. |
| Failure paths | Malformed LLM output produces a failed call while preserving the transcript. An injected embedding failure preserves call transforms, records public SDK operation diagnostics, returns 503 when query embedding also fails, and omits missing vectors when query embedding recovers. Silence makes no LLM calls. |
| Reference request contract | 7 tests passed with a substituted database dependency: input rejection, semantic failure reporting, flagged filtering beyond the old prefix, and audio response type. This is not a live Celery/Postgres processing run. |
| Comparison and lesson harness | 24 tests passed, including cache reset, source fingerprint, immutable evolution reports, collision/failure/interruption, lesson service isolation, one-fixture upload, and repeat-seed behavior. Launcher commands and HTTP providers were substituted; this does not claim a live Docker/model lesson run. All five evolution patches pass read-only applicability checks; contexts were refreshed for category validation and the explicit full-profile branch. |
| Source quality and generated evidence | Lint, whitespace checks, refreshed source metrics, and regenerated document/chart checks passed. Latency/evolution JSON was retained, not remeasured. |
| Real Pixeltable serving | The initial full-profile review passed schema/service checks, schema application/agreement, service startup, and empty-state HTTP checks in an isolated catalog. Core schema/service declaration checks also passed in a new temporary home, whose daemon was stopped afterwards. No model-backed upload was sent to either service. |
| Shared frontend | Production build and lint passed. Synthetic core/full/failed views were checked on desktop and approximately 500-pixel browser views. Core hides omitted assessments; unavailable results stay explicit, the narrow layout leads with summary before playback, and collapsed required metadata expands/focuses invalid Agent ID input. The earlier pass also exercised recording selection, Space-key transcript selection, comment anchoring, long Unicode text, labeled inputs, and media error states. The browser clamped a requested narrower viewport; this is not a claim of full device coverage or a real provider run. |

CI now uses frozen locks, runs Reference contract tests, and runs Pixeltable schema/integration smoke checks on relevant pull requests as well as the existing schedule. The GitHub-hosted workflows themselves were not executed from this local review.

## Remaining deployment and research boundaries

1. **Durable intake and admission.** The current local Pixeltable service persists fsynced media and SQLite receipts before acceptance, bounds accepted pending work, deduplicates request keys, and reconciles after restart. These guarantees depend on one writer and one retained local spool/catalog. Multipart body parsing, preaccept staging, total disk retention, request rate, and exactly-once external model side effects are not bounded or guaranteed. The Reference still needs a tested database-to-broker handoff and worker/broker recovery policy.
2. **Index readiness.** Pixeltable's implicit embedding index can hold errors while call transforms are `completed`. `UpdateStatus` and the public `pxt.get_dir_tree()` expose operation diagnostics, but historical error counts do not indicate present per-call readiness. A recovered query provider can return fewer results while old segment vectors are still missing. New receipts now persist public insert diagnostics, exposing the last intake observation as ready/failed, or unknown for legacy rows and reconciliation without saved diagnostics. External catalog edits/recompute do not refresh that observation; continuous readiness verification is still separate. Replacing the existing index would require an intentional index rebuild; this review did not silently perform that migration or use private SDK internals.
3. **External deployment.** The app has no authentication, tenancy, request/rate control, validated backup/restore, or externally tested scaling. Accepted-work admission is bounded locally. Health endpoints do not prove provider tokens, model downloads, diarization permission, and cold model loading will succeed. The local showcase is the verified operating envelope.
4. **Fresh runtime comparisons.** The committed timing/evolution JSON was collected on Pixeltable 0.7.11. Current source counts are refreshed, but the 0.7.16 latency, evolution, real-provider parity, outage recovery, and throughput experiments must be rerun before publishing new performance claims. Patch applicability was checked; the model-backed experiments were not executed.
5. **Hardware and precision controls.** The Reference chooses CPU; Pixeltable's wrappers can select available accelerators. The historical artifact does not identify the execution device per model, and the vector-index defaults can differ in precision. Future controlled studies should record and align devices, precision, batch sizes, model digests, and cache policy, or report those differences as part of each implementation.
6. **Model quality.** Roles are heuristic and ASR is configured for two speakers across all verticals. Fixtures include synthetic audio, repeated excerpts, and fictional metadata; they are behavior fixtures rather than independent ground-truth evaluation data. Sentiment/QA scores and generated recommendations need task-specific labeled evaluation before business use.
7. **Previously reported SDK issues.** The older `revert()` and query-construction observations are documented as 0.7.11 observations. They were not revalidated as 0.7.16 defects, and no current capability claim depends on them.

For developers, the next exercise is the [rule walkthrough](WALKTHROUGH.md), including explicit recompute, preservation, and quality limits. For researchers, it is a fresh controlled comparison on 0.7.16 with recorded execution settings and an independently labeled corpus. Those tasks have observable outcomes and preserve the showcase's focus on reusable backend foundations.

## Latest-release and live validation - October 9, 2026

Pixeltable 0.7.16 was released during this follow-up, so the dependency floor, lock, installed environment, and CI release assertion were updated again. Schema/service checks, isolated core service startup, and the full/core offline contracts passed on that release. The additional failed-summary extension regression verifies that the exercise refuses incomplete evidence before adding a field or comment. The timing harness now reserves a new report before work, records each attempted call and section, and preserves partial results and failures without merging historical data. Its script regressions also cover an HTTP 500 during outage recovery: a failed model load cannot look healthy, and recovery must reach a completed call. The outage container can be selected with `OLLAMA_CONTAINER` for an isolated study. All 35 script tests passed.

The real six-second billing fixture used WhisperX, pyannote, local Ollama, and sentence-transformer providers in a new temporary home. The existing Hugging Face token passed both model gates. ASR produced two timestamped segments and the expected billing/refund speech. Summary generation failed because Ollama's llama-server was killed while loading llama3.1; a summary-only retry also failed with one cell exception. The CLI exited zero despite that cell error, so both its diagnostics and the HTTP call status were checked. The call remained failed, with its transcript preserved. The live record is [validation/2026-10-09.json](validation/2026-10-09.json). This is a recorded partial failure, not a passing end-to-end lesson or a timing comparison.

The Docker VM reported 8,307,830,784 bytes shared with other services, and the Ollama container recorded an out-of-memory kill. More model memory is required before repeating the summary; 12 GB is a proposed starting VM allocation, not a tested minimum. No existing container was recreated, stopped, or reconfigured. No additional call-side key was missing. Only the review-owned service was stopped after evidence capture. The historical runtime/evolution JSON was preserved.


## Durable local intake and zero-key product walkthrough - October 10, 2026

The release adds a small standard-library local upload spool in `backends/pixeltable/intake.py`.
SQLite transactions own admission and idempotency; UUID media files are fsynced before receipt
commit. A process-lifetime flock excludes a second service writer. Startup reconciles the canonical
call ID before a new insert, checks source/model/profile identity, and resumes only queued/running
receipts. Failed cells and failed precommit inserts remain terminal with their media retained for
explicit recovery. Delayed duplicate snapshots cannot change terminal diagnostics or resurrect
an idempotency tombstone. A retried deletion finishes receipt/media cleanup if canonical deletion
committed before a receipt failure. Pending detail bypasses catalog queries, and a real blocked-ASR
integration check confirmed that detail and merged roster remain readable during an insert.

Call detail now has additive `search_readiness` and `search_error` fields. New receipts retain the
public SDK's insert diagnostics, rather than reading private index internals. These are last-insert
observations; legacy and commit-reconciled rows remain unknown, and external recompute does not
silently turn the observation into a current audit. The shared Reference response defaults unknown.
The intentional intake differences are documented in `compare/CAPABILITY_PARITY.md`, and all
application-owned receipt code is included in refreshed source metrics. Historical benchmark and
evolution JSON remains unchanged; this release is not a fresh runtime comparison.

`npm run demo` in `frontend` provides the same dashboard and recording workspace without a backend,
keys, Docker, weights, or model calls. Saved WhisperX transcript/timestamps and the committed audio
are tied to the October 9 live record; the summary is explicitly authored for illustration because
that live summary failed. A persistent notice and provenance link disclose keyword-only search
and browser-local comments. Uploads are unavailable in example mode. Normal production builds
retain the live API, with a separate static example build. Root browser checks verified playback,
segment selection, comments after reload, keyword-result navigation, and the desktop/narrow layouts
at an actual 520 px viewport (a requested 390 px viewport was clamped). Screenshots are committed
under `docs/images`; this proves saved-example UI behavior, not successful live model computation.

The extension now starts from a plausible narrow “payment reversal” rule and broadens it to
“billing”, preserving original comments as well as its probe anchor. Its small authored quality
fixture set demonstrates overtriage and missed duplicate-charge language, with an unknown result
for absent text. The [walkthrough](WALKTHROUGH.md) links the dashboard to each source responsibility,
the live lesson, explicit recompute, and [deployment profiles](DEPLOYMENT.md).

Final focused validation passed **135 test executions** across the release suites/profiles:

| Check | Result and boundary |
|---|---|
| Durable intake | 11 tests passed, including real process exits at both commit boundaries, concurrent retries, bounded admission, writer exclusion, drift, terminal failures, stale snapshots, and diagnostics. Standard library with substituted canonical writes; no providers. |
| Full Pixeltable API | 23 tests passed; one core-only case intentionally skipped. Real temporary catalogs/columns/views/indexes/media/API with deterministic provider substitutes, plus both deletion interruption cases. |
| Core Pixeltable API | 8 selected tests passed, including optional-call omission, rule extension, original comment preservation, lexical quality limits, startup recovery, blocked-ASR visibility, and delete retries. No live providers. |
| Comparison/lesson/example harness | 37 tests passed, including lost-response seed intent reuse and recorded example media/transcript provenance. |
| Shared / Reference contracts | 47 shared and 7 Reference tests passed in the root agent's final run against the additive detail fields. Reference database/provider dependencies were substituted. |
| Frontend retry identity | 2 Node tests passed; changed same-size media bytes or normalized metadata rotate the key, and same-input failed-response retries retain it. |
| Source/service/UI checks | Full-repository lint and whitespace checks, source metric/document/chart checks, live-mode production build, static example build, and frontend lint passed. Pixeltable 0.7.16 schema and service declaration checks passed in a fresh temporary home; its review-owned daemon was stopped. These checks do not start a real-model pipeline. |

The current Pixeltable implementation measures 680 application LOC across four files, including
application-owned intake; Reference remains 1,171 LOC across 24 files and shared code is 696 LOC.
The concern classification explicitly includes the local durable receipt store. These source counts
were regenerated; benchmark/evolution JSON remained byte-for-byte unchanged from HEAD. The installed
Starlette/httpx test adapter emits its known deprecation warning in SDK API tests.

No live model requests, existing-catalog resets, private SDK index access, or PDF changes were made.
The example-mode development server was stopped after the root's browser verification; all other
pre-existing services were left untouched.
