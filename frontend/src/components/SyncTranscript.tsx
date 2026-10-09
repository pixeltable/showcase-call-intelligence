import { useEffect, useRef } from "react";
import type { Segment } from "../api/client";
import type { SentimentMoment } from "../lib/sentiment";
import { SENTIMENT_BORDER_CLASSES, segmentMomentPolarity } from "../lib/sentiment";
import { speakerLabel } from "../lib/verticals";

interface Props {
  segments: Segment[];
  vertical?: string;
  sentimentMoments?: SentimentMoment[];
  currentTime: number;
  activeSegmentId: string | null;
  highlightSegmentId?: string | null;
  onSeek: (time: number, segmentId: string) => void;
  onSelectSegment: (segment: Segment) => void;
}

function speakerColor(speaker: string): string {
  if (speaker === "AGENT") return "border-indigo-500/50 bg-indigo-950/30";
  if (speaker === "CUSTOMER") return "border-emerald-500/50 bg-emerald-950/30";
  return "border-slate-600 bg-slate-900/50";
}

export function SyncTranscript({
  segments,
  vertical,
  sentimentMoments = [],
  currentTime,
  activeSegmentId,
  highlightSegmentId,
  onSeek,
  onSelectSegment,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});

  // Scroll the transcript box only; scrollIntoView would also move the page during playback.
  useEffect(() => {
    const scrollId = activeSegmentId ?? highlightSegmentId;
    const box = containerRef.current;
    const el = scrollId ? refs.current[scrollId] : null;
    if (!box || !el) return;
    const top = el.offsetTop;
    if (top < box.scrollTop || top + el.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTo({ top: Math.max(0, top - 8), behavior: "smooth" });
    }
  }, [activeSegmentId, highlightSegmentId]);

  return (
    <div
      ref={containerRef}
      className="relative max-h-[420px] space-y-2 overflow-y-auto rounded-xl border border-slate-800 bg-slate-900/40 p-3"
    >
      {segments.map((seg) => {
        const active = seg.id === activeSegmentId || (currentTime >= seg.start_sec && currentTime <= seg.end_sec);
        const highlighted = highlightSegmentId === seg.id;
        const momentPolarity = segmentMomentPolarity(seg, sentimentMoments);
        const sentimentBorder = momentPolarity ? SENTIMENT_BORDER_CLASSES[momentPolarity] : "";
        return (
          <div
            key={seg.id}
            ref={(el) => {
              refs.current[seg.id] = el;
            }}
            role="button"
            tabIndex={0}
            onClick={() => {
              onSeek(seg.start_sec, seg.id);
              onSelectSegment(seg);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                onSeek(seg.start_sec, seg.id);
                onSelectSegment(seg);
              }
            }}
            className={`cursor-pointer rounded-lg border border-l-4 px-3 py-2 transition ${speakerColor(seg.speaker)} ${sentimentBorder} ${
              highlighted ? "ring-2 ring-amber-400" : active ? "ring-2 ring-indigo-400" : ""
            }`}
          >
            <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
              <span className="font-semibold uppercase">{speakerLabel(vertical, seg.speaker)}</span>
              <span>
                {seg.start_sec.toFixed(1)}s - {seg.end_sec.toFixed(1)}s
              </span>
            </div>
            <p className="text-sm leading-relaxed">{seg.text}</p>
          </div>
        );
      })}
    </div>
  );
}
