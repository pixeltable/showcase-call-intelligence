import type { CallDetail, CallSummary, Comment, HealthResponse, Kpis, SearchHit } from "../api/client";
import billing from "./billing.json";

export const EXAMPLE_CALL_ID = billing.id;
const savedCall = billing as CallDetail;
const COMMENTS_KEY = "call-showcase-example-comments-v1";

function comments(): Comment[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(COMMENTS_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is Comment =>
      typeof item?.id === "string" && item.call_id === EXAMPLE_CALL_ID &&
      (item.segment_id === null || savedCall.segments.some((segment) => segment.id === item.segment_id)) &&
      Number.isFinite(item.start_sec) && item.start_sec >= 0 &&
      typeof item.author === "string" && typeof item.comment === "string") : [];
  } catch {
    return [];
  }
}

export const exampleApi = {
  listCalls: async (params: Record<string, string | number | undefined> = {}): Promise<CallSummary[]> => {
    if ((params.queue && params.queue !== savedCall.queue) ||
        (params.agent_id && params.agent_id !== savedCall.agent_id) || params.sentiment_label ||
        Number(params.min_handle_time ?? -1) > (savedCall.handle_time_sec ?? 0)) return [];
    return [structuredClone(savedCall)];
  },
  getKpis: async (): Promise<Kpis> => ({ call_count: 1, avg_handle_time_sec: savedCall.handle_time_sec ?? 0,
    avg_sentiment_score: null }),
  getHealth: async (): Promise<HealthResponse> => ({status: "ok", backend: "pixeltable", enrichment_profile: "core",
    checks: { example_data: { ok: true, detail: "Saved example outputs; no live backend or model calls" } } }),
  getCall: async (id: string): Promise<CallDetail> => {
    if (id !== EXAMPLE_CALL_ID) throw new Error("Example recording not found. Return to the dashboard.");
    return {...structuredClone(savedCall), comments: comments()};
  },
  uploadCall: async (_form: FormData, _key?: string): Promise<{id: string; status: string}> => {
    throw new Error("Example-data mode cannot process uploads. Start the live lesson to use your own recordings.");
  },
  search: async (q: string): Promise<SearchHit[]> => {
    const text = q.trim().toLocaleLowerCase();
    if (!text) return [];
    return savedCall.segments.filter((segment) => segment.text.toLocaleLowerCase().includes(text)).map((segment) => ({
      call_id: savedCall.id, segment_id: segment.id, agent_id: savedCall.agent_id, queue: savedCall.queue,
      call_date: savedCall.call_date, speaker: segment.speaker, start_sec: segment.start_sec, text: segment.text,
      score: 1, match_type: "keyword", media_type: "audio", original_filename: savedCall.original_filename,
    }));
  },
  createComment: async (payload: {call_id: string; segment_id?: string; start_sec?: number;
    author: string; comment: string}): Promise<Comment> => {
    if (payload.call_id !== EXAMPLE_CALL_ID ||
        (payload.segment_id && !savedCall.segments.some((segment) => segment.id === payload.segment_id))) {
      throw new Error("Choose a segment from the example recording.");
    }
    if (!payload.author.trim() || !payload.comment.trim() || payload.author.length > 128 ||
        payload.comment.length > 10000 || !Number.isFinite(payload.start_sec ?? 0) || (payload.start_sec ?? 0) < 0) {
      throw new Error("Provide an author, comment, and valid recording time.");
    }
    const comment = {...payload, id: crypto.randomUUID(), segment_id: payload.segment_id ?? null,
      start_sec: payload.start_sec ?? 0};
    try {
      localStorage.setItem(COMMENTS_KEY, JSON.stringify([...comments(), comment]));
    } catch {
      throw new Error("Browser storage is unavailable. Allow local storage to save an example comment.");
    }
    return comment;
  },
  audioUrl: (_id: string) => "/examples/billing-inquiry-speech.wav",
  videoUrl: (_id: string) => "",
};
