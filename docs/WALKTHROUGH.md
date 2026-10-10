# From a recording to a rule you can maintain

The product proof is a recording whose transcript can be searched and reviewed, followed by a
business-rule change that reuses its stored evidence. Choose the saved example to explore the
dashboard immediately, or the live lesson to execute the Pixeltable pipeline yourself.

## Explore the dashboard without keys

From the repository, with Node.js 20+ installed:

```bash
(cd frontend && npm ci && npm run demo)
```

Open **http://127.0.0.1:5176**. Select **Open example recording**, play the six-second audio,
select a transcript segment, and add a comment. Reload: the comment still targets the same segment.
Return to the dashboard and search **billing**; selecting the result opens its moment in the recording.

![Saved example recording, transcript, authored summary, and browser-local evidence comment](images/example-workspace.jpg)

The **Example data · no live computation** notice stays visible in both views. The media is the
committed synthetic billing fixture. The transcript and timestamps are actual saved WhisperX output
from [the October 9 validation](validation/2026-10-09.json). Its Ollama summary failed with an
out-of-memory kill, so this UI uses an **authored illustrative summary** and labels it accordingly.
The example's completed state means ready to browse; it does not assert a successful live pipeline.
[Provenance](../frontend/public/examples/provenance.json) records these distinctions.

Example search is local keyword matching. It has no live embedding model or vector index. Comments
are saved in this browser's local storage; they are not sent to Pixeltable. Uploads are unavailable.
`npm run build:demo` produces a static example build; use normal `npm run build` for the live API.
The [narrow workspace](images/example-workspace-mobile.jpg) keeps the summary before the player.

## Execute the live lesson

Follow the [live setup](../README.md#run-the-first-lesson), including the Hugging Face gates and
adequate local model memory. Then:

```bash
./scripts/run_pixeltable.sh
# In another terminal:
./scripts/run_pixeltable.sh seed
```

Open **http://localhost:5175**. This uses the same dashboard with the real **:8002** API and a
separate `data/lesson/` catalog. The core profile executes ASR/diarization, one summary request,
segment expansion, and embeddings. It leaves four optional assessments null. A completed call
has stored transcript and summary; detail separately exposes the last insert's search diagnostics.

Leave a comment on the first segment before the next step. Those comments live in Pixeltable.
The seed helper saves its request key and exact metadata before uploading; if a response is lost,
running seed again reuses that intent. It does not reset the catalog or retry a failed model cell.

The recorded real-model check remains **partially failed** on the shared 8 GB Docker VM; model
access was authorized, but summary loading was killed. A passing deterministic check below verifies
the SDK reuse contract without claiming that this hardware completed the live lesson.

## Change a business rule and prove reuse

After the billing fixture has a completed summary:

```bash
./scripts/run_pixeltable.sh extend
```

[`examples/extend_call.py`](../examples/extend_call.py) is the executable walkthrough. Its temporary
`lesson_needs_billing_review` field starts by matching **payment reversal**, a narrow term absent
from the fixture. It then changes the expression to recognize **billing**:

```python
calls.add_computed_column(
    lesson_needs_billing_review=contains(calls.transcript, "payment reversal", case=False)
)
calls.alter_computed_column(
    lesson_needs_billing_review=contains(calls.transcript, "billing", case=False),
    recompute=False,
)
calls.recompute_columns("lesson_needs_billing_review")
```

Observe the printed result: `initial` and `before_recompute` are false; `after_recompute` is true.
Transcript, summary, segments, existing comments, and the probe comment's UUID anchor remain
unchanged. The helper refuses incomplete evidence, confines its CLI to the dedicated lesson home,
and removes only its temporary field and probe comment. Your original review comment remains.

Run the same helper with the real Pixeltable engine and deterministic providers, without tokens:

```bash
cd backends/pixeltable
uv sync --frozen
PXT_ENRICHMENT_PROFILE=core uv run --frozen --with pytest python -m pytest \
  tests/test_api_contract.py -q -k 'extension or rule_quality'
```

The tests count ASR, chat, and embedding invocations before and after the extension and require
zero additional calls. They check the original saved comment as well as the probe. The small
[rule fixture set](../examples/billing_rule_cases.json) also exposes two limitations: “billing is
correct” still triggers the lexical rule, and a duplicate-card-charge complaint without “billing”
does not. These authored cases are a behavior check, not a model-accuracy study.

For a lasting product field, declare the expression in `Calls` in `app.py`, review `pxt schema diff`,
apply the schema, and deliberately recompute changed expressions. Expose a user-facing field through
the shared schema, detail query, Reference implementation, and UI if parity is intended. Keep
the disposable exercise separate from a product migration. Test rule quality before using a
review flag for consequential business decisions.

## Find the source from the dashboard

| Product behavior | Source to review or extend |
|---|---|
| Recorded example, provenance, browser comments | [`frontend/src/examples`](../frontend/src/examples), [`frontend/public/examples`](../frontend/public/examples) |
| Recording upload, metadata, retry key | [`UploadForm.tsx`](../frontend/src/components/UploadForm.tsx), [`uploadIdentity.js`](../frontend/src/api/uploadIdentity.js) |
| Accepted work, queue admission, restart recovery | [`intake.py`](../backends/pixeltable/intake.py), lifecycle/upload handlers in [`app.py`](../backends/pixeltable/app.py) |
| Media/ASR/summary dependency graph | `Calls` in [`app.py`](../backends/pixeltable/app.py), [`functions.py`](../backends/pixeltable/functions.py), [`shared transforms`](../shared/call_center_api) |
| Search hit to recording moment | `TranscriptSegments`, `search()` in [`app.py`](../backends/pixeltable/app.py), [`GlobalSearch.tsx`](../frontend/src/components/GlobalSearch.tsx) |
| Evidence comment and stable segment UUID | `CoachingComments`, `create_comment()` in [`app.py`](../backends/pixeltable/app.py), [`CoachingComments.tsx`](../frontend/src/components/CoachingComments.tsx) |
| Rule extension and preservation checks | [`extend_call.py`](../examples/extend_call.py), [`test_api_contract.py`](../backends/pixeltable/tests/test_api_contract.py) |

The broader [backend mapping](../compare/BACKEND_MAPPING.md) and [capability differences](../compare/CAPABILITY_PARITY.md)
show what changes when the same product uses the Reference stack. Current code counts include the
application-owned intake; historical runtime measurements predate it.

## Observe the intake boundary

The Pixeltable upload handler writes and fsyncs media, then commits a SQLite receipt before returning
HTTP202. Its spool lives under `PXT_UPLOAD_DIR`; `.intake/receipts.sqlite3` holds receipts and
`.intake/writer.lock` excludes a second service writer. Use a separate upload directory for each
catalog/service. The startup hook resumes queued/running receipts only after checking `Calls.id`.
It checks accepted source/model/profile identity before a new insert. Changed configuration leaves
the receipt failed for operator review. After fixing or deliberately approving the configuration,
DELETE that failed call and re-upload the original file with a new key. This is a new request and
may invoke providers again; there is no implicit precommit-retry endpoint.

`Idempotency-Key` is optional. Reusing it with identical media bytes and normalized metadata returns
the same call ID; changed input returns409. The shared UI hashes actual bytes and normalized fields
and retains its key through a failed response while that form remains open; new input or success
rotates it. The Reference app currently ignores this header. A deleted Pixeltable key is a retained
tombstone and returns410; use a new key for a new call.

`PXT_MAX_PENDING_UPLOADS` defaults to eight accepted queued/running calls. A full queue returns429
with `Retry-After`; retries of an existing key still work. This bounds accepted work, not multipart
body parsing, concurrent preaccept staging, disk growth from completed/failed calls, or request rate.
Pending receipts are visible in detail and roster while model work executes. Deleting a pending
call returns409. Failed cells and precommit failures are terminal; neither restart nor an identical
upload silently runs them again. If the canonical call row exists, inspect failed cells with
`pxt errors`, and explicitly recompute the appropriate fields with `--errors-only` after fixing the
provider. For a failed receipt with no canonical row, fix the cause, DELETE the failed call to clear
its media and tombstone its key, and submit the original recording with a new key. A CLI exit code alone is insufficient;
check cell diagnostics and the HTTP call status.

Call detail's `search_readiness` records **the last intake observation**: `ready` after an insert with
no reported computed/index errors, `failed` after reported errors, `pending` while queued/running,
or `unknown` for legacy rows and commit reconciliation without saved diagnostics. Recomputing or
editing a catalog outside intake does not refresh that observation. Query embedding failures return503;
missing vectors are omitted. This is separate from the stored transform status and provider health.

The crash tests kill a process after receipt commit and after canonical-row commit before receipt
finalization, and prove one recovery insert or zero repeat inserts respectively. They also cover
concurrent duplicate requests, bounds, configuration drift, writer locks, delete cleanup, and stale
queued snapshots. They do not guarantee exactly-once external model side effects if a process dies
after a provider request but before its database row commits. Files orphaned by a crash before
receipt commit are never scheduled; inspect and remove them only while intake is stopped.

Read [DEPLOYMENT.md](DEPLOYMENT.md) for local/public profiles, authentication, secrets, single-writer
constraints, retention, and backup/restore responsibilities. No existing catalog migration, live
model request, historical-result rewrite, or public deployment is part of this release.
