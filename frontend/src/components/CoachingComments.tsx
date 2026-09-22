import type { FormEvent } from "react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { CallDetail, Segment } from "../api/client";
import { api } from "../api";

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
    if (!comment.trim()) return;
    mutation.mutate({
      call_id: call.id,
      segment_id: selectedSegment?.id,
      start_sec: selectedSegment?.start_sec ?? 0,
      author,
      comment,
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
              {c.author} · {c.start_sec.toFixed(1)}s
            </p>
            <p>{c.comment}</p>
          </li>
        ))}
        {call.comments.length === 0 && <li className="text-sm text-slate-500">No comments yet.</li>}
      </ul>
      <form onSubmit={onSubmit} className="mt-3 space-y-2">
        <input
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm"
          placeholder="Author"
        />
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-sm"
          placeholder="Great de-escalation here..."
        />
        <button type="submit" className="rounded bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500">
          Add Comment
        </button>
      </form>
    </div>
  );
}
