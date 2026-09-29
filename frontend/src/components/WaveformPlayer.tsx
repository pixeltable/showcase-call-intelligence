import { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import { SENTIMENT_REGION_COLORS } from "../lib/sentiment";

interface RegionSpec {
  start: number;
  end: number;
  color?: string;
}

interface Props {
  audioUrl: string;
  regions?: RegionSpec[];
  currentTime: number;
  onTimeUpdate: (time: number) => void;
  onReady?: (seek: (time: number) => void, playClip: (startSec: number, endSec: number) => void) => void;
  /** When false, waveform is cursor-only (muted); an external player drives currentTime. */
  drivePlayback?: boolean;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function WaveformPlayer({
  audioUrl,
  regions = [],
  currentTime,
  onTimeUpdate,
  onReady,
  drivePlayback = true,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<RegionsPlugin | null>(null);
  const onReadyRef = useRef(onReady);
  const onTimeUpdateRef = useRef(onTimeUpdate);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [duration, setDuration] = useState(0);
  const [displayTime, setDisplayTime] = useState(0);

  useEffect(() => {
    onReadyRef.current = onReady;
    onTimeUpdateRef.current = onTimeUpdate;
  }, [onReady, onTimeUpdate]);

  useEffect(() => {
    if (!containerRef.current) return;

    const regionsPlugin = RegionsPlugin.create();
    regionsRef.current = regionsPlugin;
    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "#475569",
      progressColor: "#818cf8",
      cursorColor: "#e2e8f0",
      height: 96,
      url: audioUrl,
      plugins: [regionsPlugin],
    });

    if (drivePlayback) {
      ws.on("timeupdate", (time) => {
        setDisplayTime(time);
        onTimeUpdateRef.current(time);
      });
      ws.on("play", () => setIsPlaying(true));
      ws.on("pause", () => setIsPlaying(false));
      ws.on("finish", () => setIsPlaying(false));
    } else {
      ws.setVolume(0);
    }

    ws.on("ready", () => {
      if (!drivePlayback) ws.setVolume(0);
      setDuration(ws.getDuration());
      setDisplayTime(ws.getCurrentTime());
      setIsReady(true);
      const seek = (time: number) => ws.setTime(time);
      const playClip = (startSec: number, endSec: number) => {
        void ws.play(startSec, endSec);
      };
      onReadyRef.current?.(seek, playClip);
    });

    wsRef.current = ws;
    return () => {
      ws.destroy();
      wsRef.current = null;
      regionsRef.current = null;
      setIsPlaying(false);
      setIsReady(false);
    };
  }, [audioUrl, drivePlayback]);

  // Regions change without reloading the audio.
  useEffect(() => {
    const plugin = regionsRef.current;
    if (!plugin || !isReady) return;
    plugin.clearRegions();
    regions.forEach((r) =>
      plugin.addRegion({
        start: r.start,
        end: r.end,
        color: r.color ?? "rgba(239, 68, 68, 0.25)",
        drag: false,
        resize: false,
      }),
    );
  }, [regions, isReady]);

  useEffect(() => {
    const ws = wsRef.current;
    if (!ws) return;
    if (Math.abs(ws.getCurrentTime() - currentTime) > 0.3) {
      ws.setTime(currentTime);
      if (drivePlayback) setDisplayTime(currentTime);
    }
  }, [currentTime, drivePlayback]);

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-2">
      {drivePlayback && (
        <div className="mb-2 flex items-center gap-3 px-1">
          <button
            type="button"
            aria-label={isPlaying ? "Pause" : "Play"}
            onClick={() => wsRef.current?.playPause()}
            className="rounded bg-indigo-600 px-3 py-1 text-sm font-medium text-white hover:bg-indigo-500"
          >
            {isPlaying ? "Pause" : "Play"}
          </button>
          <span className="text-xs tabular-nums text-slate-400">
            {formatTime(displayTime)} / {formatTime(duration)}
          </span>
        </div>
      )}
      <div ref={containerRef} />
      {regions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-3 px-1 text-xs text-slate-400">
          {(Object.keys(SENTIMENT_REGION_COLORS) as Array<keyof typeof SENTIMENT_REGION_COLORS>).map((key) => (
            <span key={key} className="inline-flex items-center gap-1 capitalize">
              <span
                className="inline-block h-2 w-4 rounded-sm"
                style={{ backgroundColor: SENTIMENT_REGION_COLORS[key] }}
              />
              {key}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
