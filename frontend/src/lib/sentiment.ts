import type { Segment } from "../api/client";

export type SentimentPolarity = "positive" | "neutral" | "negative";

export interface SentimentMoment {
  start_sec?: number;
  end_sec?: number;
  polarity?: SentimentPolarity | string;
  reason?: string;
}

export const SENTIMENT_REGION_COLORS: Record<SentimentPolarity, string> = {
  negative: "rgba(239, 68, 68, 0.25)",
  neutral: "rgba(234, 179, 8, 0.25)",
  positive: "rgba(34, 197, 94, 0.25)",
};

export const SENTIMENT_CHIP_CLASSES: Record<SentimentPolarity, string> = {
  negative: "bg-red-950/30 text-red-200",
  neutral: "bg-amber-950/30 text-amber-200",
  positive: "bg-green-950/30 text-green-200",
};

export const SENTIMENT_BORDER_CLASSES: Record<SentimentPolarity, string> = {
  negative: "border-l-red-500/70",
  neutral: "border-l-amber-500/70",
  positive: "border-l-green-500/70",
};

function normalizePolarity(value: string | undefined): SentimentPolarity {
  if (value === "positive" || value === "neutral" || value === "negative") return value;
  return "negative";
}

/** Read moments from API sentiment JSON, including legacy flags as negative moments. */
export function sentimentMoments(sentiment: Record<string, unknown> | null | undefined): SentimentMoment[] {
  if (!sentiment) return [];
  const rawMoments = sentiment.moments;
  if (Array.isArray(rawMoments) && rawMoments.length > 0) {
    return rawMoments.filter((m): m is SentimentMoment => typeof m === "object" && m !== null);
  }
  const rawFlags = sentiment.flags;
  if (Array.isArray(rawFlags)) {
    return rawFlags
      .filter((m): m is SentimentMoment => typeof m === "object" && m !== null)
      .map((m) => ({ ...m, polarity: "negative" as const }));
  }
  return [];
}

export function momentPolarity(moment: SentimentMoment): SentimentPolarity {
  return normalizePolarity(typeof moment.polarity === "string" ? moment.polarity : undefined);
}

export function momentRegion(
  moment: SentimentMoment,
  segments: Segment[] = [],
): { start: number; end: number; color: string; polarity: SentimentPolarity } | null {
  if (moment.start_sec == null) return null;
  const polarity = momentPolarity(moment);
  let start = moment.start_sec;
  let end = moment.end_sec ?? moment.start_sec + 2;
  if (moment.end_sec == null) {
    start = Math.max(0, moment.start_sec - 1);
    end = moment.start_sec + 2;
  }
  const overlapping = segments.find(
    (seg) => seg.start_sec <= moment.start_sec! && seg.end_sec >= moment.start_sec!,
  );
  if (overlapping && moment.end_sec == null) {
    start = overlapping.start_sec;
    end = overlapping.end_sec;
  }
  return { start, end, color: SENTIMENT_REGION_COLORS[polarity], polarity };
}

export function segmentMomentPolarity(
  segment: Segment,
  moments: SentimentMoment[],
): SentimentPolarity | null {
  for (const moment of moments) {
    if (moment.start_sec == null) continue;
    const start = moment.start_sec;
    const end = moment.end_sec ?? moment.start_sec + 2;
    if (segment.start_sec <= end && segment.end_sec >= start) {
      return momentPolarity(moment);
    }
  }
  return null;
}
