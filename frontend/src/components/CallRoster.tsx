import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { TERMINAL_STATUSES, api } from "../api/client";
import { getProfile } from "../lib/verticals";

const POLL_MS = 3000;

function sentimentClass(label: string | null): string {
  if (label === "negative") return "bg-red-500/20 text-red-300";
  if (label === "positive") return "bg-green-500/20 text-green-300";
  if (label === "neutral") return "bg-yellow-500/20 text-yellow-300";
  return "bg-slate-700 text-slate-300";
}

interface Props {
  onSelect: (id: string) => void;
  sentimentFilter: string;
  queueFilter: string;
  /** Uploaded ids not yet listed as done. A backend may list a call only once processing finishes. */
  pendingIds: string[];
  onSettled: (ids: string[]) => void;
}

export function CallRoster({ onSelect, sentimentFilter, queueFilter, pendingIds, onSettled }: Props) {
  const { data: calls = [], isLoading, isError, error } = useQuery({
    queryKey: ["calls", sentimentFilter, queueFilter],
    queryFn: () =>
      api.listCalls({
        sentiment_label: sentimentFilter || undefined,
        queue: queueFilter || undefined,
        limit: 100,
      }),
    refetchInterval: (query) => {
      const rows = query.state.data ?? [];
      const processing = rows.some((c) => !TERMINAL_STATUSES.has(c.status));
      return processing || pendingIds.length > 0 ? POLL_MS : false;
    },
  });

  useEffect(() => {
    const done = calls.filter((c) => pendingIds.includes(c.id) && TERMINAL_STATUSES.has(c.status)).map((c) => c.id);
    if (done.length > 0) onSettled(done);
  }, [calls, pendingIds, onSettled]);

  const headerLabels = getProfile(calls[0]?.vertical).labels;
  const waiting = pendingIds.filter((id) => !calls.some((c) => c.id === id)).length;

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
      {isError && (
        <p className="border-b border-red-900/50 bg-red-950/30 px-3 py-2 text-sm text-red-400">
          {error instanceof Error ? error.message : "Failed to load recordings."}
        </p>
      )}
      {waiting > 0 && (
        <p className="border-b border-slate-800 px-3 py-2 text-sm text-slate-400">
          {waiting} upload{waiting > 1 ? "s" : ""} processing. {waiting > 1 ? "They appear" : "It appears"} here when
          the backend lists {waiting > 1 ? "them" : "it"}.
        </p>
      )}
      {isLoading && <p className="px-3 py-4 text-center text-sm text-slate-400">Loading recordings...</p>}
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
          {calls.map((call) => (
            <tr
              key={call.id}
              onClick={() => onSelect(call.id)}
              className="cursor-pointer border-t border-slate-800 hover:bg-slate-800/50"
            >
              <td className="px-3 py-2">{new Date(call.call_date).toLocaleString()}</td>
              <td className="px-3 py-2">
                <span className="rounded bg-slate-800 px-2 py-0.5 text-xs">{getProfile(call.vertical).displayName}</span>
              </td>
              <td className="px-3 py-2">{call.agent_id}</td>
              <td className="px-3 py-2">{call.customer_id}</td>
              <td className="px-3 py-2">{call.queue}</td>
              <td className="px-3 py-2">{call.handle_time_sec != null ? `${call.handle_time_sec.toFixed(0)}s` : "-"}</td>
              <td className="px-3 py-2">{call.category ?? "-"}</td>
              <td className="px-3 py-2">
                <span className={`rounded px-2 py-0.5 text-xs ${sentimentClass(call.sentiment_label)}`}>
                  {call.sentiment_label ?? "-"}
                </span>
              </td>
              <td className="px-3 py-2 capitalize">{call.status}</td>
            </tr>
          ))}
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
