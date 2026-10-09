import { useQuery } from "@tanstack/react-query";
import type { Kpis } from "../api/client";
import { api } from "../api/client";
import { DEFAULT_VERTICAL, getProfile } from "../lib/verticals";

export function KpiBanner() {
  const { data, isError, error } = useQuery({ queryKey: ["kpis"], queryFn: api.getKpis, refetchInterval: 10000 });
  const { data: calls = [] } = useQuery({
    queryKey: ["calls", "", ""],
    queryFn: () => api.listCalls({ limit: 100 }),
  });

  const kpis: Kpis = data ?? { call_count: 0, avg_handle_time_sec: 0, avg_sentiment_score: 0 };
  const dominantVertical =
    calls.length > 0
      ? calls.reduce<Record<string, number>>((acc, call) => {
          const key = call.vertical || DEFAULT_VERTICAL;
          acc[key] = (acc[key] ?? 0) + 1;
          return acc;
        }, {})
      : {};
  const topVertical = Object.entries(dominantVertical).sort((a, b) => b[1] - a[1])[0]?.[0];
  const labels = getProfile(topVertical).labels;

  return (
    <div className="grid grid-cols-3 gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      {isError && (
        <p className="col-span-3 text-sm text-red-400">
          {error instanceof Error ? error.message : "Failed to load KPIs."}
        </p>
      )}
      <div>
        <p className="text-xs uppercase tracking-wide text-slate-400">{labels.kpiRecordings}</p>
        <p className="text-2xl font-semibold">{kpis.call_count}</p>
      </div>
      <div>
        <p className="text-xs uppercase tracking-wide text-slate-400">{labels.kpiDuration}</p>
        <p className="text-2xl font-semibold">{kpis.avg_handle_time_sec.toFixed(0)}</p>
      </div>
      <div>
        <p className="text-xs uppercase tracking-wide text-slate-400">Avg sentiment</p>
        <p className="text-2xl font-semibold">{kpis.avg_sentiment_score.toFixed(2)}</p>
      </div>
    </div>
  );
}
