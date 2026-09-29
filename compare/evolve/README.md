# Changes to a running system

Patches that [`scripts/bench_evolve.py`](../../scripts/bench_evolve.py) applies to the working tree, times, verifies over HTTP and reverts. None of them is committed into the backends, so [`scripts/metrics.py`](../../scripts/metrics.py) keeps measuring the product. Results: [`../results/evolve.json`](../results/evolve.json).

| Patch | Change |
|---|---|
| `topics-shared.patch` | The contract part of a new LLM field, `topics`: its prompt, its parser, and the field in `CallDetail`. Both backends need it; it is charged to neither. |
| `topics-pixeltable.patch` | Pixeltable's part: a computed column, its parse UDF, the field in the detail query. |
| `topics-reference.patch` | The Reference's part: model column, Alembic migration, enrichment code, task code, route, and a backfill task. |
| `summary-prompt-shared.patch` | A new summary prompt, read by both backends. |
| `summary-rerun-reference.patch` | The task the Reference needs to re-run only the summary. Pixeltable needs no code: `pxt recompute call_center/calls summary`. |

The third experiment, recovering from an LLM outage, needs no patch on either side: it stops this repo's Ollama container while a call is processed and uses each backend's existing recovery path.

Each patch applies to the tree it is published with. After changing a file one touches, make the change again on a clean tree and save it with `git diff > compare/evolve/<name>.patch`, so `git apply --check` passes.
