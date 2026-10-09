import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function KpiBanner({ showEnrichments = true }: { showEnrichments?: boolean }) {
  const { data, isError, error } = useQuery({ queryKey: ["kpis"], queryFn: api.getKpis, refetchInterval: 10000 });

  return (
    <div aria-label="Recording metrics" aria-busy={!data && !isError} className="flex flex-wrap gap-x-12 gap-y-4 py-4">
      {isError && (
        <p role="alert" className="w-full text-sm text-red-400">
          {error instanceof Error ? error.message : "Failed to load KPIs."}
        </p>
      )}
      <div>
        <p className="text-sm text-slate-400">Completed recordings (7d)</p>
        <p className="text-2xl font-semibold">{data?.call_count ?? "—"}</p>
      </div>
      <div>
        <p className="text-sm text-slate-400">Average duration (seconds)</p>
        <p className="text-2xl font-semibold">{data && data.call_count > 0 ? data.avg_handle_time_sec.toFixed(0) : "—"}</p>
      </div>
      {showEnrichments && <div>
        <p className="text-sm text-slate-400">Average model sentiment</p>
        <p className="text-2xl font-semibold">{data && data.call_count > 0 && data.avg_sentiment_score != null ? data.avg_sentiment_score.toFixed(2) : "—"}</p>
      </div>}
    </div>
  );
}
