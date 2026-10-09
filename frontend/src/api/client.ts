export interface CallSummary {
  id: string;
  call_date: string;
  agent_id: string;
  customer_id: string;
  queue: string;
  vertical: string;
  duration_sec: number | null;
  handle_time_sec: number | null;
  status: string;
  category: string | null;
  summary: string | null;
  sentiment_label: string | null;
  sentiment_score: number | null;
  media_type: "audio" | "video";
  has_video_source: boolean;
}

export interface Segment {
  id: string;
  speaker: string;
  start_sec: number;
  end_sec: number;
  text: string;
}

export interface Comment {
  id: string;
  call_id: string;
  segment_id: string | null;
  start_sec: number;
  author: string;
  comment: string;
}

export interface CallDetail extends CallSummary {
  original_filename: string;
  action_items: string[] | null;
  sentiment: Record<string, unknown> | null;
  qa_scorecard: Record<string, unknown> | null;
  error_message: string | null;
  segments: Segment[];
  comments: Comment[];
}

export interface Kpis {
  call_count: number;
  avg_handle_time_sec: number;
  avg_sentiment_score: number;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  backend: "reference" | "pixeltable";
  checks: Record<string, { ok: boolean; detail?: string | null }>;
}

export interface SearchHit {
  call_id: string;
  segment_id: string;
  agent_id: string;
  queue: string;
  call_date: string;
  speaker: string;
  start_sec: number;
  text: string;
  score: number | null;
  match_type: "keyword" | "semantic";
  media_type: "audio" | "video";
  original_filename: string;
}

export const TERMINAL_STATUSES = new Set(["completed", "failed"]);

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const raw = await res.text();
    let message = raw || res.statusText;
    try {
      const parsed = JSON.parse(raw) as { detail?: string | Array<{ msg?: string }> };
      if (typeof parsed.detail === "string") {
        message = parsed.detail;
      } else if (Array.isArray(parsed.detail)) {
        message = parsed.detail.map((d) => d.msg ?? JSON.stringify(d)).join("; ");
      }
    } catch {
      /* use raw text */
    }
    throw new ApiError(message || `Request failed (${res.status}).`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Routes Pixeltable declares with `add_query_route` wrap rows in `{rows: [...]}`; the Reference returns a list. */
async function requestRows<T>(path: string): Promise<T[]> {
  const body = await request<T[] | { rows: T[] }>(path);
  return Array.isArray(body) ? body : body.rows;
}

export const api = {
  listCalls: (params: Record<string, string | number | undefined> = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    return requestRows<CallSummary>(`/api/calls?${qs}`);
  },
  getKpis: () => request<Kpis>("/api/calls/kpis"),
  getHealth: () => request<HealthResponse>("/api/health"),
  getCall: (id: string) => request<CallDetail>(`/api/calls/${id}`),
  uploadCall: (form: FormData) =>
    request<{ id: string; status: string }>("/api/calls/upload", { method: "POST", body: form }),
  search: (q: string) => requestRows<SearchHit>(`/api/search?q=${encodeURIComponent(q)}&mode=hybrid`),
  createComment: (payload: {
    call_id: string;
    segment_id?: string;
    start_sec?: number;
    author: string;
    comment: string;
  }) =>
    request<Comment>("/api/comments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  audioUrl: (id: string) => `/api/calls/${id}/audio`,
  videoUrl: (id: string) => `/api/calls/${id}/video`,
};
