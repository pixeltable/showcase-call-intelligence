# Call intelligence: Pixeltable vs. a vibe-coded backend

[![CI](https://github.com/pixeltable/showcase-call-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/pixeltable/showcase-call-intelligence/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

One call review application, built two ways. Upload audio or video, get a speaker-labelled transcript and summary, search the conversation, and leave coaching comments on the exact moment.

A coding agent can build the first demo quickly. This repository asks what you have to maintain when the product changes: model pipelines, media, indexes, backfills, and recovery. [Pixeltable](https://github.com/pixeltable/pixeltable) gives the agent those backend foundations so it can spend more effort on your features and business rules.

## Compare what you maintain

- **Pixeltable:** Python `TableModel` classes, typed audio/video, computed columns, an embedding index, and `FastAPIRouter`. The schema declares the processing dependencies.
- **Custom Reference:** an AI-assisted implementation using FastAPI, SQLAlchemy, Alembic, Celery, Redis, and Postgres/pgvector. Application code coordinates stages, status, migrations, backfills, and repairs.

Both serve the same **React / TypeScript / Vite UI and REST contract**, using **WhisperX**, **Ollama / Llama 3.1**, and **SentenceTransformers**.

<!-- results:readme-code -->
| Backend application | Custom Reference | Pixeltable |
|---|---|---|
| Code lines | 1,171 | 680 |
| Files | 24 | 4 |
<!-- /results:readme-code -->

Counts cover backend application code; shared code, tests, dependencies, and configuration are excluded. The [comparison and methodology](compare/RESULTS.md) cover adding a field, changing a summary prompt, and recovering from an LLM outage. This is one concrete custom implementation; the [tradeoffs](compare/WHY_PIXELTABLE.md#where-the-reference-is-ahead) include concurrency and progress reporting.

## Walk through the app

1. **Ingest a recording.** Extract audio, transcribe, identify speakers, summarize, and index timestamped segments. The full profile adds action items, sentiment, categories, and QA scorecards.
2. **Find the evidence.** Search a phrase or meaning and jump to the matching moment in the player.
3. **Review it.** Attach a coaching comment to a segment.
4. **Change a rule.** Add a billing-review field, then update it while reusing the stored transcript and preserving comment anchors.

The [live walkthrough](docs/WALKTHROUGH.md#execute-the-live-lesson) runs this pipeline; the [extension lesson](docs/WALKTHROUGH.md#change-a-business-rule-and-prove-reuse) checks that the rule change makes no additional transcription, summary, or embedding calls.

## Try it

With Node.js 20+, explore the saved example without a backend, keys, or model downloads:

```bash
git clone https://github.com/pixeltable/showcase-call-intelligence.git
cd showcase-call-intelligence
(cd frontend && npm ci && npm run demo)
```

Open **http://127.0.0.1:5176**. Play the recording, search "billing", and add a comment. This preview uses a recorded transcript, an authored illustrative summary, and browser-local keyword search and comments. Use the live walkthrough for real model calls and semantic search.

![Call recording with transcript, summary, and an anchored coaching comment](docs/images/example-workspace.jpg)

## Build your next feature

Start with [`backends/pixeltable/app.py`](backends/pixeltable/app.py), then give your agent the [Pixeltable skill](https://github.com/pixeltable/pixeltable-skill) and a product rule to implement. Inspect the [Reference backend](backends/reference) to compare the work behind the same feature. The motivation: [why vibe-coded AI apps become hard to maintain](https://www.pixeltable.com/blog/vibe-coded-ai-apps-break-production).

Current code targets **Pixeltable 0.7.16**; published runtime measurements used **0.7.11**. This is a local, single-tenant showcase. Upload admission and recovery remain application code; see [deployment](docs/DEPLOYMENT.md) and [validation limits](docs/REVIEW.md).

[Contributing and checks](CONTRIBUTING.md) · [More example apps](https://github.com/pierrebrunelle/awesome-pixeltable-apps)
