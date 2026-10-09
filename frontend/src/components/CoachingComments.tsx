import type { FormEvent } from "react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { CallDetail, Segment } from "../api/client";
import { api } from "../api/client";

interface Props {
  call: CallDetail;
  selectedSegment: Segment | null;
}

export function CoachingComments({ call, selectedSegment }: Props) {
  const qc = useQueryClient();
  const [author, setAuthor] = useState("qa-reviewer");
  const [comment, setComment] = useState("");

  const mutation = useMutation({
    mutationFn: api.createComment,
    onSuccess: () => {
      setComment("");
      qc.invalidateQueries({ queryKey: ["call", call.id] });
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!comment.trim() || !author.trim() || mutation.isPending) return;
    mutation.mutate({
      call_id: call.id,
      segment_id: selectedSegment?.id,
      start_sec: selectedSegment?.start_sec ?? 0,
      author: author.trim(),
      comment: comment.trim(),
    });
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h3 className="text-sm font-semibold">Coaching Comments</h3>
      {selectedSegment && (
        <p className="mt-1 text-xs text-slate-400">
          Anchored to {selectedSegment.speaker} @ {selectedSegment.start_sec.toFixed(1)}s
        </p>
      )}
      <ul className="mt-3 space-y-2">
        {call.comments.map((c) => (
          <li key={c.id} className="rounded border border-slate-800 bg-slate-950/50 p-2 text-sm">
            <p className="text-xs text-slate-400">
              {c.author} · {c.start_sec.toFixed(1)}s{c.segment_id ? " · on a segment" : ""}
            </p>
            <p>{c.comment}</p>
          </li>
        ))}
        {call.comments.length === 0 && <li className="text-sm text-slate-500">No comments yet.</li>}
      </ul>
      <form onSubmit={onSubmit} className="mt-3 space-y-2">
        <input
          aria-label="Comment author"
          required
          maxLength={128}
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm"
          placeholder="Author"
        />
        <textarea
          aria-label="Coaching comment"
          required
          maxLength={10000}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm"
          placeholder="Great de-escalation here..."
        />
        <button
          type="submit"
          disabled={mutation.isPending || !comment.trim() || !author.trim()}
          className="rounded bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500 disabled:opacity-50"
        >
          {mutation.isPending ? "Saving..." : "Add Comment"}
        </button>
        {mutation.isError && (
          <p role="alert" className="text-sm text-red-400">
            {mutation.error instanceof Error ? mutation.error.message : "Failed to save comment."}
          </p>
        )}
      </form>
    </div>
  );
}
