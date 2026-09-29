import type { FormEvent } from "react";
import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { DEFAULT_VERTICAL, VERTICAL_OPTIONS, getProfile } from "../lib/verticals";

// Mirrors ALLOWED_UPLOAD_EXTENSIONS in shared/call_center_api/constants.py.
const ACCEPT = ".wav,.mp3,.m4a,.ogg,.flac,.webm,.mp4,.mov,.mkv";

function localDateTimeValue(date: Date): string {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

interface Props {
  onUploaded?: (callId: string) => void;
}

export function UploadForm({ onUploaded }: Props) {
  const qc = useQueryClient();
  const formRef = useRef<HTMLFormElement>(null);
  const [status, setStatus] = useState("");
  const [vertical, setVertical] = useState(DEFAULT_VERTICAL);
  const labels = getProfile(vertical).labels;

  const mutation = useMutation({
    mutationFn: (form: FormData) => api.uploadCall(form),
    onSuccess: ({ id }) => {
      setStatus("Upload queued. Processing in the background.");
      formRef.current?.reset();
      setVertical(DEFAULT_VERTICAL);
      onUploaded?.(id);
      qc.invalidateQueries({ queryKey: ["calls"] });
      qc.invalidateQueries({ queryKey: ["kpis"] });
    },
    onError: (err: Error) => setStatus(err.message),
  });

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    // datetime-local has no offset; send an absolute instant so both backends store the same time.
    form.set("call_date", new Date(String(form.get("call_date"))).toISOString());
    setStatus("Uploading...");
    mutation.mutate(form);
  }

  return (
    <form ref={formRef} onSubmit={onSubmit} className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h2 className="text-lg font-semibold">{labels.uploadTitle}</h2>
      <label className="block text-sm">
        Use case
        <select
          name="vertical"
          value={vertical}
          onChange={(e) => setVertical(e.target.value as typeof vertical)}
          className="mt-1 block w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
        >
          {VERTICAL_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.displayName}
            </option>
          ))}
        </select>
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="block text-sm">
          Recording (audio or video)
          <input type="file" name="audio" accept={ACCEPT} required className="mt-1 block w-full text-sm" />
        </label>
        <label className="block text-sm">
          Recording date
          <input
            type="datetime-local"
            name="call_date"
            required
            defaultValue={localDateTimeValue(new Date())}
            className="mt-1 block w-full rounded border border-slate-700 bg-slate-950 px-2 py-1"
          />
        </label>
        <label className="block text-sm">
          {labels.agentId}
          <input name="agent_id" required placeholder="agent-101" className="mt-1 block w-full rounded border border-slate-700 bg-slate-950 px-2 py-1" />
        </label>
        <label className="block text-sm">
          {labels.customerId}
          <input name="customer_id" required placeholder="cust-4821" className="mt-1 block w-full rounded border border-slate-700 bg-slate-950 px-2 py-1" />
        </label>
        <label className="block text-sm md:col-span-2">
          {labels.queue}
          <input name="queue" required placeholder="billing" className="mt-1 block w-full rounded border border-slate-700 bg-slate-950 px-2 py-1" />
        </label>
      </div>
      <button
        type="submit"
        disabled={mutation.isPending}
        className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
      >
        {mutation.isPending ? "Uploading..." : "Upload & Process"}
      </button>
      {status && <p className="text-sm text-slate-400">{status}</p>}
    </form>
  );
}
