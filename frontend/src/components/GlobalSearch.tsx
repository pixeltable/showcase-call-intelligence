import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { SearchHit } from "../api/client";
import { api } from "../api";

const PAGE_SIZE = 5;

interface Props {
  onSelectCall: (callId: string, startSec?: number, segmentId?: string) => void;
}

function matchBadge(matchType: SearchHit["match_type"]) {
  if (matchType === "semantic") {
    return (
      <span className="rounded bg-violet-500/20 px-1.5 py-0.5 text-[10px] uppercase text-violet-300">
        semantic
      </span>
    );
  }
  return (
    <span className="rounded bg-sky-500/20 px-1.5 py-0.5 text-[10px] uppercase text-sky-300">
      keyword
    </span>
  );
}

export function GlobalSearch({ onSelectCall }: Props) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [page, setPage] = useState(1);

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.getHealth(),
    staleTime: 60_000,
  });

  const embedCheck = health?.checks.embed_model;
  const semanticUnavailable = embedCheck?.ok === false;

  const { data: results = [], isFetching, isError, error } = useQuery({
    queryKey: ["search", submitted],
    queryFn: () => api.search(submitted),
    enabled: submitted.length > 0,
  });

  useEffect(() => {
    setPage(1);
  }, [submitted]);

  const total = results.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageStart = (safePage - 1) * PAGE_SIZE;
  const pageResults = results.slice(pageStart, pageStart + PAGE_SIZE);

  const keywordOnlyResults =
    submitted.length > 0 &&
    results.length > 0 &&
    results.every((hit) => hit.match_type === "keyword");

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(query.trim());
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h2 className="mb-2 text-lg font-semibold">Global Search</h2>
      {semanticUnavailable && (
        <p className="mb-2 rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
          Semantic search may be unavailable — {embedCheck?.detail ?? "embedding model not ready"}. Keyword
          matches still work. Ensure <code className="text-amber-100">EMBED_MODEL</code> is installed, then
          re-seed or backfill embeddings.
        </p>
      )}
      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='e.g. "cancel my subscription"'
          className="flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
        <button type="submit" className="rounded bg-slate-700 px-4 py-2 text-sm hover:bg-slate-600">
          Search
        </button>
      </form>
      {isFetching && <p className="mt-2 text-sm text-slate-400">Searching...</p>}
      {isError && (
        <p className="mt-2 text-sm text-red-400">
          Search failed: {error instanceof Error ? error.message : "Unknown error"}
        </p>
      )}
      {!isFetching && !isError && submitted && results.length === 0 && (
        <p className="mt-2 text-sm text-slate-400">No results for &ldquo;{submitted}&rdquo;.</p>
      )}
      {!semanticUnavailable && !isFetching && !isError && keywordOnlyResults && (
        <p className="mt-2 text-sm text-slate-400">
          Showing keyword matches. Hybrid search also adds semantically related segments from other calls when
          they do not contain your exact query text.
        </p>
      )}
      <ul className="mt-3 space-y-2">
        {pageResults.map((hit: SearchHit) => (
          <li key={`${hit.call_id}-${hit.segment_id}`}>
            <button
              type="button"
              onClick={() => onSelectCall(hit.call_id, hit.start_sec, hit.segment_id)}
              className="w-full rounded border border-slate-800 bg-slate-950/50 p-3 text-left hover:border-indigo-500"
            >
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span>
                  {hit.agent_id} · {hit.queue} · {new Date(hit.call_date).toLocaleString()}
                </span>
                {matchBadge(hit.match_type)}
                {hit.media_type === "video" && (
                  <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] uppercase text-amber-300">
                    video
                  </span>
                )}
                {hit.original_filename && (
                  <span className="truncate text-slate-500">{hit.original_filename}</span>
                )}
                {hit.score != null && hit.match_type === "semantic" && (
                  <span className="text-slate-500">score {hit.score.toFixed(3)}</span>
                )}
              </div>
              <p className="mt-1 text-sm">
                <span className="font-medium text-indigo-300">{hit.speaker}</span>: {hit.text}
              </p>
            </button>
          </li>
        ))}
      </ul>
      {!isFetching && !isError && total > PAGE_SIZE && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3">
          <p className="text-sm text-slate-400">
            Showing {pageStart + 1}–{Math.min(pageStart + PAGE_SIZE, total)} of {total} results
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:border-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:border-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
