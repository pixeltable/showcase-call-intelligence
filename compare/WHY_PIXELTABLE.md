# What Pixeltable gives you, and what the Reference had to build

The Reference is one implementation built with an AI coding assistant using FastAPI, SQLAlchemy, Alembic, Celery, Redis, Postgres, and pgvector. It is the concrete baseline in this repository, rather than a claim about every generated backend. Both implementations have the same parity gates ([CAPABILITY_PARITY.md](CAPABILITY_PARITY.md)). This page shows what each side owns and how the historical run measured changes to live data. Measured rows come from [`results/`](results/); hand-classified rows say so. How it was measured: [METHODOLOGY.md](METHODOLOGY.md).

## Measured from source

<!-- results:code -->
| Measured from source | Reference | Pixeltable |
|---|---|---|
| App code you maintain (lines) | 1,171 | 442 |
| Files | 24 | 3 |
| Project config files: pyproject.toml, alembic.ini (lines) | 59 | 20 |
| Tables | 3 | 2 |
| Views | n/a | 1 |
| Vector indexes | 1 | 1 |
| Migration files | 3 | n/a |
| Task-queue tasks | 4 | n/a |
| Status writes in pipeline code | 11 | n/a |
| Routes with a hand-written handler | 15 | 10 |
| Routes declared from a query | n/a | 2 |
| Orchestration hops | 50 | 13 |
| Processes to run (hand-classified) | 4 | 1 |
<!-- /results:code -->

Where the lines go (files grouped by concern by hand; the counts are measured):

<!-- results:concerns -->
| Concern (hand-classified; lines measured) | Reference | Pixeltable |
|---|---|---|
| Schema and pipeline | 483 | 173 |
| &nbsp;&nbsp;of which schema and migrations | 211 |  |
| &nbsp;&nbsp;of which model and media wrappers | 175 |  |
| &nbsp;&nbsp;of which orchestration and status | 97 |  |
| Queries and HTTP | 469 | 258 |
| Repair tooling | 187 | n/a |
| Settings (config.py) | 32 | 11 |
| **Total** | **1,171** | **442** |
<!-- /results:concerns -->

The HTTP layer is where the two are closest: both hand-write handlers for the same REST contract, and Pixeltable's are shorter because its queries name columns the way the contract does and the list routes are declared. The difference is the rest: the Reference writes the pipeline's orchestration, its state machine, its schema history, its model wrappers and the tools to repair what the pipeline can leave half-done. On Pixeltable those are the table definitions.

## Measured by changing the running system

Two changes and one failure a team meets in the first month, run against both backends with the ten seeded calls in place. The shared part of each change (a prompt, a parser, a field in the contract) is the same for both and is reported separately.

<!-- results:evolve -->
|  | Reference | Pixeltable |
|---|---|---|
| **Add `topics` to live data** |  |  |
| Lines written (backend) | 50 | 6 |
| Files touched (backend) | 8 | 2 |
| Operator steps | alembic upgrade head: add the column (1s)<br>restart the API and the Celery worker (9s)<br>run the backfill task over every processed call (58s) | restart the pxt daemon (shared module changed) (2s)<br>pxt schema update: add the column, backfill every row (54s)<br>pxt service update: serve the new column (11s) |
| Wall time | 68s | 67s |
| Existing calls with topics (of 10) | 10 | 10 |
| New uploads get topics | yes | yes |
| **Re-run only the summary after a prompt change** |  |  |
| Lines written (backend) | 30 | 0 |
| Operator steps | restart the API and the Celery worker (9s)<br>run the re-summarize task over every processed call (92s) | restart the pxt daemon (shared module changed) (2s)<br>pxt recompute calls summary: one LLM call per row (109s)<br>pxt service restart: new uploads use the new prompt (9s) |
| Wall time | 101s | 120s |
| Summaries changed (of 10) | 10 | 10 |
| Transcripts untouched | 10 | 10 |
| Coaching comment still anchored | yes | yes |
| **Reference without new code: re-queue `process_call`** |  |  |
| Wall time | 722s |  |
| Transcripts untouched | 0 |  |
| Coaching comment still anchored | **no** |  |
| **Recover from an LLM outage during processing** |  |  |
| State after the outage | failed, 2 segments kept | failed, 2 segments kept |
| Where the error is recorded | the call's `status` and `error_message` | `errormsg` on `action_items`, `category`, `qa_scorecard`, `sentiment`, `summary` |
| Recovery code that had to exist | 80 lines (`resume_call.py`) | 0 lines |
| Operator steps | run the resume task written for this (resume_call.py) (26s) | pxt errors: which cells failed (0s)<br>pxt recompute summary --errors-only (5s)<br>pxt recompute action_items --errors-only (2s)<br>pxt recompute sentiment --errors-only (8s)<br>pxt recompute category --errors-only (2s)<br>pxt recompute qa_scorecard --errors-only (5s) |
| Wall time | 26s | 22s |
| Completed, transcript untouched | yes | yes |
| Searchable again | yes | yes |
<!-- /results:evolve -->

**Adding a field to live data.** Pixeltable: one computed column, one parse UDF, one line in the detail query; `pxt schema update` adds the column and fills it for every existing call in the same step, and new uploads compute it on insert. Reference: a model column, an Alembic migration, the enrichment code, the task code that copies results onto the row, the route, and a backfill task written for the occasion, then a migration, a worker restart and a backfill run.

**Recovering from an LLM outage.** Ollama stops while a call is processed. Both backends keep the transcript, mark the call `failed` and leave it out of search until it recovers. The Reference records one `status` and one `error_message`, and getting the call back needs `resume_call.py`, which the generated stack already grew for exactly this. Pixeltable stores the row with its segments and their embeddings and records the error on the five LLM cells alone; `pxt errors` lists them and `pxt recompute ... --errors-only` re-runs those cells and nothing else. The same thing happened for real while seeding this repo: Ollama ran out of memory during one call's `category` request, and one `pxt recompute call_center/calls category --errors-only` brought it back.

**Re-running one step.** After a prompt change, `pxt recompute call_center/calls summary` calls the LLM once per call and rewrites only `summary`; transcripts, segments, embeddings and comment anchors are untouched. The Reference has no such path. Its existing option is to re-queue `process_call`, which re-transcribes, deletes and re-creates every segment (so a coaching comment's segment anchor is set to NULL by the foreign key), re-runs all five enrichments and re-embeds. Doing better means writing a task for it, the re-summarize task measured above.

## Capability by capability

| What you need | Pixeltable | Reference |
|---|---|---|
| Run the pipeline on every new call | The insert is the trigger, from HTTP, the CLI, a notebook or another service | Only callers that go through `upload_call` enqueue `process_call`; a row written any other way stays `queued` |
| Orchestrate the steps | Computed columns; Pixeltable orders them from their inputs | A Celery app, a Redis broker, a task that commits a status after each stage |
| Know what failed, and where | `errormsg` / `errortype` on each cell; `pxt errors call_center/calls` | One `status` and one `error_message` per call |
| Retry only what failed | `pxt recompute call_center/calls summary --errors-only` | `resume_call.py`, `embed_maintenance.py` and admin routes, written for it |
| Change the schema of live data | Edit the class, `pxt schema update`; additive changes apply and backfill, destructive ones need `--allow-destructive` | Model edit, migration file, `alembic upgrade`, backfill code |
| Semantic search | `EmbeddingIndex` on the segment view; the index follows inserts and deletes, and `similarity(string=q)` embeds the query with the same model | `vector(768)` column and HNSW index in a migration, an embed step in the task, query embedding by hand, re-embed and backfill tasks for vectors the task failed to write |
| Search results with call context | The segment view carries its call's columns | A join per query |
| Video | `pxt.Video` column, `extract_audio` computed column, stored and cleaned up by Pixeltable | ffmpeg subprocess, output paths, cleanup on delete |
| History | Every insert, update and recompute is a table version (`pxt history call_center/calls`); older versions are queryable as `call_center.calls:N` | None (Postgres point-in-time recovery is not configured) |
| Lineage | `pxt computed call_center/calls` lists every column with its expression; `pxt dashboard` shows table and column lineage and version history | The pipeline is the code of one task |
| Services to run (hand-classified) | `pxt service` | API, Celery worker, Postgres, Redis |

## Where the Reference is ahead

- **Progress.** It commits a status after each stage, so a user sees `transcribing` and `enriching` and the roster lists a call from the moment it is uploaded. A Pixeltable row commits only when every column is computed; until then the API can only say `processing`, and the roster shows the call when it is done.
- **Throughput under load.** Pixeltable's insert holds the `calls` table lock for the whole computation, so inserts into one table run one at a time. Celery runs as many calls at once as it has workers. This comparison runs one at a time on both sides, which hides the difference.
- **Writes during processing.** On Pixeltable a delete or a schema change waits for the insert in progress. The Reference is not blocked.
- **Backfill failure.** The Reference's backfill task commits call by call. `pxt schema update` backfills in one transaction, so one failing LLM call rolls back the whole column.
- **A durable call record.** The Reference commits a `queued` row before publishing to Celery, so the record survives an API restart. Its database commit and broker publish are separate, Redis persistence is not configured, and tasks use early acknowledgement; automatic recovery across broker or worker failure is not guaranteed. The Pixeltable app holds an accepted upload in memory until its row commits: restarting the service in between loses the call (its id returns 404) and leaves the upload on disk. Closing that gap requires a durable intake and tested recovery path; Pixeltable's own background insert routes also keep jobs in memory.
- **Read latency.** Building a Pixeltable query resolves the table once per selected expression, a cost SQLAlchemy queries do not pay. The declared routes match the Reference, and the handlers that reuse a select list come close; semantic search, whose select list depends on the request, stays slower ([METHODOLOGY.md](METHODOLOGY.md#pixeltable-issues-this-comparison-hit)).
- **Familiarity.** Every piece of the Reference is a tool most backend engineers already know.
- **Undo in the historical run.** The 0.7.11 run observed a view-row issue after `pxt revert` ([METHODOLOGY.md](METHODOLOGY.md#pixeltable-issues-this-comparison-hit)). That behavior has not been revalidated on 0.7.15; the comparison does not depend on it.

## Neither has

Auth, multi-tenancy, realtime push to the UI, and a pipeline that scales past one machine.
