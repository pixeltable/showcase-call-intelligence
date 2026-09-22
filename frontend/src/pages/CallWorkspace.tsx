import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { Segment } from "../api/client";
import { api } from "../api";
import { CoachingComments } from "../components/CoachingComments";
import { IntelligenceSidebar } from "../components/IntelligenceSidebar";
import { SyncTranscript } from "../components/SyncTranscript";
import { VideoPlayer } from "../components/VideoPlayer";
import { WaveformPlayer } from "../components/WaveformPlayer";
import { momentRegion, sentimentMoments } from "../lib/sentiment";
import { getProfile } from "../lib/verticals";

export function CallWorkspace() {
  const { callId } = useParams<{ callId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTime = Number(searchParams.get("t") ?? "0");
  const highlightSegmentId = searchParams.get("seg");
  const waveformSeekRef = useRef<(time: number) => void>(() => {});
  const videoSeekRef = useRef<(time: number) => void>(() => {});
  const videoPlayClipRef = useRef<(startSec: number, endSec: number) => void>(() => {});
  const audioPlayClipRef = useRef<(startSec: number, endSec: number) => void>(() => {});

  const [currentTime, setCurrentTime] = useState(initialTime);
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [videoError, setVideoError] = useState(false);

  const { data: call, isLoading, error } = useQuery({
    queryKey: ["call", callId],
    queryFn: () => api.getCall(callId!),
    enabled: !!callId,
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && status !== "completed" && status !== "failed" ? 3000 : false;
    },
  });

  const hasVideoSource = call?.has_video_source ?? false;

  const mediaSeek = useCallback(
    (time: number) => {
      waveformSeekRef.current(time);
      if (hasVideoSource) videoSeekRef.current(time);
    },
    [hasVideoSource],
  );

  useEffect(() => {
    if (!call || !highlightSegmentId) return;
    const seg = call.segments.find((s) => s.id === highlightSegmentId);
    if (seg) setSelectedSegment(seg);
  }, [call, highlightSegmentId]);

  useEffect(() => {
    if (searchParams.get("t") === null && !highlightSegmentId) return;
    const t = Number(searchParams.get("t") ?? "0");
    setCurrentTime(t);
    mediaSeek(t);
  }, [searchParams, highlightSegmentId, mediaSeek]);

  const activeSegmentId = useMemo(() => {
    if (highlightSegmentId && call?.segments.some((s) => s.id === highlightSegmentId)) {
      return highlightSegmentId;
    }
    if (!call?.segments.length) return null;
    const match = call.segments.find((s) => currentTime >= s.start_sec && currentTime <= s.end_sec);
    return match?.id ?? null;
  }, [call, currentTime, highlightSegmentId]);

  const regions = useMemo(() => {
    const moments = sentimentMoments(call?.sentiment ?? null);
    return moments
      .map((moment) => momentRegion(moment, call?.segments ?? []))
      .filter((region): region is NonNullable<typeof region> => region !== null);
  }, [call]);

  const updateSeekParams = (time: number, segmentId: string) => {
    setSearchParams({ t: String(time), seg: segmentId }, { replace: true });
  };

  if (isLoading) return <p className="p-6 text-slate-400">Loading call...</p>;
  if (error || !call) {
    const message = error instanceof Error ? error.message : "Failed to load call.";
    return <p className="p-6 text-red-400">{message}</p>;
  }

  const profile = getProfile(call.vertical);

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/" className="text-sm text-indigo-400 hover:underline">
            ← Back to dashboard
          </Link>
          <h1 className="mt-1 text-2xl font-bold">
            {call.agent_id} · {call.queue}
          </h1>
          <p className="text-sm text-slate-400">
            {call.customer_id} · {new Date(call.call_date).toLocaleString()} ·{" "}
            <span className="capitalize">{call.status}</span>
            {call.original_filename && (
              <>
                {" "}
                · <span className="text-slate-500">{call.original_filename}</span>
              </>
            )}
          </p>
          <div className="mt-1 flex flex-wrap gap-2">
            <span className="rounded bg-indigo-500/20 px-2 py-0.5 text-xs text-indigo-200">
              {profile.displayName}
            </span>
            <span className="rounded bg-slate-800 px-2 py-0.5 text-xs uppercase text-slate-300">
              {call.media_type}
            </span>
            {call.has_video_source && (
              <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs uppercase text-amber-300">
                source video
              </span>
            )}
          </div>
        </div>
        <span
          className={`rounded px-3 py-1 text-sm ${
            call.sentiment?.label === "negative"
              ? "bg-red-500/20 text-red-300"
              : call.sentiment?.label === "positive"
                ? "bg-green-500/20 text-green-300"
                : "bg-yellow-500/20 text-yellow-300"
          }`}
        >
          {String(call.sentiment?.label ?? "unknown")}
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {call.status === "completed" ? (
            <>
              {call.has_video_source && (
                <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
                  <p className="mb-2 text-sm font-medium text-slate-300">Source video</p>
                  {videoError ? (
                    <p className="text-sm text-red-400">Video unavailable.</p>
                  ) : (
                    <VideoPlayer
                      videoUrl={api.videoUrl(call.id)}
                      currentTime={currentTime}
                      onTimeUpdate={setCurrentTime}
                      onError={() => setVideoError(true)}
                      onReady={(seek, playClip) => {
                        videoSeekRef.current = seek;
                        videoPlayClipRef.current = playClip;
                        if (!Number.isNaN(initialTime)) seek(initialTime);
                      }}
                    />
                  )}
                </div>
              )}
              <WaveformPlayer
                audioUrl={api.audioUrl(call.id)}
                regions={regions}
                currentTime={currentTime}
                onTimeUpdate={hasVideoSource ? () => {} : setCurrentTime}
                drivePlayback={!hasVideoSource}
                onReady={(seek, playClip) => {
                  waveformSeekRef.current = seek;
                  if (!hasVideoSource) {
                    audioPlayClipRef.current = playClip;
                  }
                  if (!Number.isNaN(initialTime)) seek(initialTime);
                }}
              />
            </>
          ) : call.status === "failed" ? (
            <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-6 text-sm">
              <p className="font-medium text-red-300">Call processing failed</p>
              {call.error_message && <p className="mt-2 text-red-400">{call.error_message}</p>}
            </div>
          ) : (
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-6 text-sm text-slate-400">
              Processing call ({call.status})...
            </div>
          )}

          <SyncTranscript
            segments={call.segments}
            vertical={call.vertical}
            sentimentMoments={sentimentMoments(call.sentiment ?? null)}
            currentTime={currentTime}
            activeSegmentId={activeSegmentId}
            highlightSegmentId={highlightSegmentId}
            onSeek={(time, segmentId) => {
              const seg = call.segments.find((s) => s.id === segmentId);
              setCurrentTime(time);
              mediaSeek(time);
              updateSeekParams(time, segmentId);
              setSelectedSegment(seg ?? null);
              if (hasVideoSource && seg) {
                videoPlayClipRef.current(time, seg.end_sec);
              } else if (seg) {
                audioPlayClipRef.current(time, seg.end_sec);
              }
            }}
            onSelectSegment={setSelectedSegment}
          />

          <CoachingComments call={call} selectedSegment={selectedSegment} />
        </div>

        <IntelligenceSidebar call={call} />
      </div>
    </div>
  );
}
