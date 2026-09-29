import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
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

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold">Conversation Intelligence</h1>
          {health && (
            <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
              {BACKEND_LABEL[health.backend]}
            </span>
          )}
        </div>
        <p className="text-slate-400">
          Upload recordings from call centers, sales, podcasts, or interviews. Triage signals and search transcripts.
        </p>
      </header>

      <KpiBanner />

      <div className="grid gap-6 lg:grid-cols-2">
        <UploadForm onUploaded={(id) => setPendingIds((ids) => [...ids, id])} />
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

      <div className="flex flex-wrap gap-3">
        <select
          value={sentimentFilter}
          onChange={(e) => setSentimentFilter(e.target.value)}
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        >
          <option value="">All sentiments</option>
          <option value="negative">Negative</option>
          <option value="neutral">Neutral</option>
          <option value="positive">Positive</option>
        </select>
        <input
          value={queueInput}
          onChange={(e) => setQueueInput(e.target.value)}
          placeholder="Filter by queue / stage / series"
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
      </div>

      <CallRoster
        onSelect={(id) => navigate(`/calls/${id}`)}
        sentimentFilter={sentimentFilter}
        queueFilter={queueFilter}
        pendingIds={pendingIds}
        onSettled={settle}
      />
    </div>
  );
}
