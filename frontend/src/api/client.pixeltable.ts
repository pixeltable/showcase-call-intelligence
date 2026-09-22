import type {
  CallDetail,
  CallSummary,
  Comment,
  HealthResponse,
  Kpis,
  SearchHit,
  Segment,
} from "./client";
import { segmentUuid } from "../lib/segmentId";

interface RowsResponse<T> {
  rows: T[];
}

interface NativeCallRow {
  uuid: string;
  call_date: string;
  agent_id: string;
  customer_id: string;
  queue: string;
  vertical: string;
  duration_sec: number | null;
  handle_time_sec: number | null;
  pipeline_status: string;
  category: string | null;
  summary: string | null;
  sentiment: { label?: string; score?: number; moments?: unknown[] } | null;
  media_type: "audio" | "video";
  has_video_source?: boolean;
  original_filename?: string;
  action_items?: string[] | null;
  qa_scorecard?: Record<string, unknown> | null;
  segments?: Array<Record<string, unknown>> | null;
  diarized_err?: string | null;
  summary_err?: string | null;
  sentiment_err?: string | null;
  action_items_err?: string | null;
  category_err?: string | null;
  qa_err?: string | null;
  audio_url?: string | null;
  video_url?: string | null;
}

interface NativeCommentRow {
  uuid: string;
  call_uuid: string;
  segment_pos: number | null;
  start_sec: number;
  author: string;
  comment: string;
  timestamp: string;
}

interface NativeSearchRow {
  call_uuid: string;
  segment_pos: number;
  agent_id: string;
  customer_id: string;
  queue: string;
  call_date: string;
  speaker: string;
  start_sec: number;
  end_sec: number;
  text: string;
  score?: number | null;
  match_type?: "keyword" | "semantic";
  media_type?: "audio" | "video";
  original_filename?: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const raw = await res.text();
    throw new Error(raw || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

function firstError(row: NativeCallRow): string | null {
  for (const key of [
    "diarized_err",
    "summary_err",
    "sentiment_err",
    "action_items_err",
    "category_err",
    "qa_err",
  ] as const) {
    const value = row[key];
    if (value && String(value).trim()) {
      return String(value).trim();
    }
  }
  return null;
}

function mapSummary(row: NativeCallRow): CallSummary {
  const sentiment = row.sentiment;
  return {
    id: row.uuid,
    call_date: row.call_date,
    agent_id: row.agent_id,
    customer_id: row.customer_id,
    queue: row.queue,
    vertical: row.vertical,
    duration_sec: row.duration_sec,
    handle_time_sec: row.handle_time_sec,
    status: firstError(row) ? "failed" : row.pipeline_status,
    category: row.category,
    summary: row.summary,
    sentiment_label: sentiment?.label ?? null,
    sentiment_score: sentiment?.score ?? null,
    media_type: row.media_type ?? "audio",
    has_video_source: Boolean(row.has_video_source),
  };
}

function mapSegments(callId: string, segments: Array<Record<string, unknown>> | null | undefined): Segment[] {
  if (!segments) return [];
  return segments.map((seg, idx) => ({
    id: segmentUuid(callId, idx),
    speaker: String(seg.speaker ?? "UNKNOWN"),
    start_sec: Number(seg.start_sec ?? 0),
    end_sec: Number(seg.end_sec ?? 0),
    text: String(seg.text ?? ""),
    pos: idx,
  }));
}

function mapComment(row: NativeCommentRow): Comment {
  const pos = row.segment_pos;
  return {
    id: row.uuid,
    call_id: row.call_uuid,
    segment_id: pos != null && pos >= 0 ? segmentUuid(row.call_uuid, pos) : null,
    start_sec: row.start_sec,
    author: row.author,
    comment: row.comment,
    created_at: row.timestamp,
  };
}

function mapSearchHit(row: NativeSearchRow, matchType: "keyword" | "semantic"): SearchHit {
  return {
    call_id: row.call_uuid,
    segment_id: segmentUuid(row.call_uuid, row.segment_pos),
    agent_id: row.agent_id,
    customer_id: row.customer_id,
    queue: row.queue,
    call_date: row.call_date,
    speaker: row.speaker,
    start_sec: row.start_sec,
    end_sec: row.end_sec,
    text: row.text,
    score: row.score ?? null,
    segment_pos: row.segment_pos,
    match_type: row.match_type ?? matchType,
    media_type: row.media_type ?? "audio",
    original_filename: row.original_filename ?? "",
  };
}

export const pxtApi = {
  listCalls: async (params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    const res = await request<RowsResponse<NativeCallRow>>(`/api/calls?${qs}`);
    let rows = res.rows.map(mapSummary);
    const sentimentLabel = params.sentiment_label;
    if (sentimentLabel) {
      rows = rows.filter((row) => row.sentiment_label === sentimentLabel);
    }
    return rows;
  },
  getKpis: () => request<Kpis>("/api/calls/kpis"),
  getHealth: () => request<HealthResponse>("/api/health"),
  getCall: async (id: string): Promise<CallDetail> => {
    const row = await request<NativeCallRow>(`/api/calls/${id}`);
    const commentsRes = await request<RowsResponse<NativeCommentRow>>(`/api/comments/call/${id}`);
    const error = firstError(row);
    return {
      ...mapSummary(row),
      audio_path: row.audio_url ?? `/api/calls/${id}/audio`,
      original_filename: row.original_filename ?? "",
      action_items: row.action_items ?? null,
      sentiment: row.sentiment ?? null,
      qa_scorecard: row.qa_scorecard ?? null,
      error_message: error,
      segments: mapSegments(id, row.segments),
      comments: commentsRes.rows.map(mapComment),
    };
  },
  uploadCall: async (form: FormData) => {
    const callId = crypto.randomUUID();
    form.set("uuid", callId);
    const file = form.get("audio") as File | null;
    const suffix = file?.name?.split(".").pop()?.toLowerCase() ?? "wav";
    // .webm is audio per shared/call_center_api/constants.py (ALLOWED_AUDIO_EXTENSIONS)
    const isVideo = ["mp4", "mov", "mkv"].includes(suffix);
    form.set("media_type", isVideo ? "video" : "audio");
    if (file && !form.get("original_filename")) {
      form.set("original_filename", file.name);
    }
    await request<{ id: string; status: string }>("/api/calls/upload", {
      method: "POST",
      body: form,
    });
    return { id: callId, status: "queued" };
  },
  search: async (q: string, mode = "hybrid") => {
    const rows = await request<NativeSearchRow[]>(
      `/api/search?q=${encodeURIComponent(q)}&mode=${mode}`,
    );
    return rows.map((row) => mapSearchHit(row, row.match_type ?? "keyword"));
  },
  createComment: async (payload: {
    call_id: string;
    segment_id?: string;
    start_sec?: number;
    author: string;
    comment: string;
  }) => {
    let segment_pos = -1;
    if (payload.segment_id) {
      const detail = await request<NativeCallRow>(`/api/calls/${payload.call_id}`);
      const count = detail.segments?.length ?? 0;
      const pos = Number(payload.segment_id.split(":").pop());
      if (Number.isInteger(pos) && pos >= 0 && pos < count) {
        segment_pos = pos;
      }
    }
    const created = await request<NativeCommentRow>("/api/comments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        call_uuid: payload.call_id,
        segment_pos,
        start_sec: payload.start_sec ?? 0,
        author: payload.author,
        comment: payload.comment,
      }),
    });
    return mapComment(created);
  },
  audioUrl: (id: string) => `/api/calls/${id}/audio`,
  videoUrl: (id: string) => `/api/calls/${id}/video`,
};
