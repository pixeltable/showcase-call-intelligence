import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, EXAMPLE_DATA } from "../api/client";
import { EXAMPLE_CALL_ID } from "../examples/exampleApi";
import { CallRoster } from "../components/CallRoster";
import { GlobalSearch } from "../components/GlobalSearch";
import { KpiBanner } from "../components/KpiBanner";
import { UploadForm } from "../components/UploadForm";

const BACKEND_LABEL = { reference: "Reference: Celery + Postgres", pixeltable: "Pixeltable" } as const;

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export function Dashboard() {
  const navigate = useNavigate();
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [queueInput, setQueueInput] = useState("");
  const queueFilter = useDebounced(queueInput.trim(), 300);
  // Uploads this session is waiting on; the roster keeps polling until each one is listed and done.
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const settle = useCallback((done: string[]) => setPendingIds((ids) => ids.filter((id) => !done.includes(id))), []);
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.getHealth, staleTime: 60_000 });
  const showEnrichments = health?.enrichment_profile !== "core";

  return (
    <main className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold">Conversation Intelligence</h1>
          {health && (
            <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
              {EXAMPLE_DATA ? "Example data" : BACKEND_LABEL[health.backend]}
            </span>
          )}
        </div>
        <p className="text-slate-400">
          Start with one recording. Review its summary, search the transcript, and leave a comment at a specific moment.
        </p>
        <a href="https://github.com/pixeltable/showcase-call-intelligence/blob/main/docs/WALKTHROUGH.md"
          className="mt-2 inline-block text-sm text-indigo-300 underline underline-offset-4">Developer walkthrough and source map</a>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        {EXAMPLE_DATA ? <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h2 className="text-lg font-semibold">Explore a billing conversation</h2>
          <p className="max-w-prose text-sm text-slate-300">Play the six-second recording, find “billing” in the transcript,
            and attach a review note to the evidence. This saved example needs no keys or model downloads.</p>
          <button type="button" onClick={() => navigate(`/calls/${EXAMPLE_CALL_ID}`)}
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500">Open example recording</button>
          <p className="text-sm text-slate-400">Use the live lesson to process your own uploads and run semantic search.</p>
        </section> : <UploadForm onUploaded={(id) => setPendingIds((ids) => [...ids, id])} />}
        <GlobalSearch
          onSelectCall={(callId, startSec, segmentId) => {
            const params = new URLSearchParams();
            if (startSec != null) params.set("t", String(startSec));
            if (segmentId) params.set("seg", segmentId);
            const qs = params.toString();
            navigate(`/calls/${callId}${qs ? `?${qs}` : ""}`);
          }}
        />
      </div>

      <details className="border-y border-slate-800 py-3">
        <summary className="cursor-pointer text-sm text-slate-300">Recording metrics and filters</summary>
        <KpiBanner showEnrichments={showEnrichments} />
        {showEnrichments && <p className="mb-3 text-sm text-slate-400">Sentiment and review scores are model estimates for this example. They have not been calibrated for business decisions.</p>}
        <div className="flex flex-wrap gap-3">
        {showEnrichments && <select
          aria-label="Filter recordings by sentiment"
          value={sentimentFilter}
          onChange={(e) => setSentimentFilter(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm sm:w-80"
        >
          <option value="">All sentiments</option>
          <option value="negative">Negative</option>
          <option value="neutral">Neutral</option>
          <option value="positive">Positive</option>
        </select>}
        <input
          aria-label="Filter recordings by group"
          value={queueInput}
          onChange={(e) => setQueueInput(e.target.value)}
          placeholder="Queue, stage, series, or role"
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm sm:w-80"
        />
      </div>
      </details>

      <CallRoster
        onSelect={(id) => navigate(`/calls/${id}`)}
        sentimentFilter={showEnrichments ? sentimentFilter : ""}
        queueFilter={queueFilter}
        pendingIds={pendingIds}
        onSettled={settle}
        showEnrichments={showEnrichments}
      />
    </main>
  );
}
