import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CallRoster } from "../components/CallRoster";
import { GlobalSearch } from "../components/GlobalSearch";
import { KpiBanner } from "../components/KpiBanner";
import { UploadForm } from "../components/UploadForm";

export function Dashboard() {
  const navigate = useNavigate();
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [queueFilter, setQueueFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header>
        <h1 className="text-3xl font-bold">Conversation Intelligence</h1>
        <p className="text-slate-400">
          Upload recordings from call centers, sales, podcasts, or interviews — triage signals and search transcripts.
        </p>
      </header>

      <KpiBanner />

      <div className="grid gap-6 lg:grid-cols-2">
        <UploadForm />
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
          value={queueFilter}
          onChange={(e) => setQueueFilter(e.target.value)}
          placeholder="Filter by queue / stage / series"
          className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
      </div>

      <CallRoster
        selectedId={selectedId}
        onSelect={(id) => {
          setSelectedId(id);
          navigate(`/calls/${id}`);
        }}
        sentimentFilter={sentimentFilter}
        queueFilter={queueFilter}
      />
    </div>
  );
}
