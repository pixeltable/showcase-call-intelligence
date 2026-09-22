import { useQuery } from "@tanstack/react-query";
import type { CallSummary } from "../api/client";
import { api } from "../api";
import { getProfile } from "../lib/verticals";

function sentimentClass(label: string | null): string {
  if (label === "negative") return "bg-red-500/20 text-red-300";
  if (label === "positive") return "bg-green-500/20 text-green-300";
  if (label === "neutral") return "bg-yellow-500/20 text-yellow-300";
  return "bg-slate-700 text-slate-300";
}

interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
  sentimentFilter: string;
  queueFilter: string;
}

export function CallRoster({ selectedId, onSelect, sentimentFilter, queueFilter }: Props) {
  const { data: calls = [], isLoading, isError, error } = useQuery({
    queryKey: ["calls", sentimentFilter, queueFilter],
    queryFn: () =>
      api.listCalls({
        sentiment_label: sentimentFilter || undefined,
        queue: queueFilter || undefined,
        limit: 100,
      }),
    refetchInterval: (query) => {
      const rows = query.state.data as CallSummary[] | undefined;
      const pending = rows?.some((c) => ["queued", "transcribing", "diarizing", "enriching", "embedding"].includes(c.status));
      return pending ? 3000 : false;
    },
  });

  const headerLabels = getProfile(calls[0]?.vertical).labels;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      {isError && (
        <p className="border-b border-red-900/50 bg-red-950/30 px-3 py-2 text-sm text-red-400">
          {error instanceof Error ? error.message : "Failed to load recordings."}
        </p>
      )}
      {isLoading && (
        <p className="px-3 py-4 text-center text-sm text-slate-400">Loading recordings...</p>
      )}
      <table className="min-w-full text-sm">
        <thead className="bg-slate-900 text-left text-xs uppercase text-slate-400">
          <tr>
            <th className="px-3 py-2">Date</th>
            <th className="px-3 py-2">Type</th>
            <th className="px-3 py-2">{headerLabels.rosterAgent}</th>
            <th className="px-3 py-2">{headerLabels.rosterCustomer}</th>
            <th className="px-3 py-2">{headerLabels.rosterQueue}</th>
            <th className="px-3 py-2">Duration</th>
            <th className="px-3 py-2">Category</th>
            <th className="px-3 py-2">Sentiment</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => {
            const profile = getProfile(call.vertical);
            return (
              <tr
                key={call.id}
                onClick={() => onSelect(call.id)}
                className={`cursor-pointer border-t border-slate-800 hover:bg-slate-800/50 ${
                  selectedId === call.id ? "bg-indigo-950/40" : ""
                }`}
              >
                <td className="px-3 py-2">{new Date(call.call_date).toLocaleString()}</td>
                <td className="px-3 py-2">
                  <span className="rounded bg-slate-800 px-2 py-0.5 text-xs">{profile.displayName}</span>
                </td>
                <td className="px-3 py-2">{call.agent_id}</td>
                <td className="px-3 py-2">{call.customer_id}</td>
                <td className="px-3 py-2">{call.queue}</td>
                <td className="px-3 py-2">{call.handle_time_sec?.toFixed(0) ?? "—"}s</td>
                <td className="px-3 py-2">{call.category ?? "—"}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${sentimentClass(call.sentiment_label)}`}>
                    {call.sentiment_label ?? "—"}
                  </span>
                </td>
                <td className="px-3 py-2 capitalize">{call.status}</td>
              </tr>
            );
          })}
          {calls.length === 0 && !isLoading && !isError && (
            <tr>
              <td colSpan={9} className="px-3 py-6 text-center text-slate-400">
                No recordings yet. Upload one to get started.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
