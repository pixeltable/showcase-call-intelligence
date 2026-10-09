import { useEffect, useRef, useState } from "react";

interface Props {
  videoUrl: string;
  currentTime: number;
  onTimeUpdate: (time: number) => void;
  onReady?: (seek: (time: number) => void, playClip: (startSec: number, endSec: number) => void) => void;
  onError?: () => void;
}

export function VideoPlayer({
  videoUrl,
  currentTime,
  onTimeUpdate,
  onReady,
  onError,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const clipEndRef = useRef<number | null>(null);
  const onTimeUpdateRef = useRef(onTimeUpdate);
  const onReadyRef = useRef(onReady);
  const [playbackError, setPlaybackError] = useState(false);

  useEffect(() => {
    onTimeUpdateRef.current = onTimeUpdate;
  }, [onTimeUpdate]);

  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const seek = (time: number) => {
      if (!Number.isFinite(time)) return;
      if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
        video.currentTime = time;
      } else {
        video.addEventListener("loadedmetadata", () => (video.currentTime = time), { once: true });
      }
    };
    const playClip = (startSec: number, endSec: number) => {
      clipEndRef.current = endSec;
      seek(startSec);
      setPlaybackError(false);
      void video.play().catch(() => setPlaybackError(true));
    };

    onReadyRef.current?.(seek, playClip);

    const handleTimeUpdate = () => {
      const t = video.currentTime;
      onTimeUpdateRef.current(t);
      const end = clipEndRef.current;
      if (end != null && t >= end) {
        video.pause();
        clipEndRef.current = null;
      }
    };

    video.addEventListener("timeupdate", handleTimeUpdate);
    return () => video.removeEventListener("timeupdate", handleTimeUpdate);
  }, [videoUrl]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (Number.isFinite(currentTime) && video.readyState >= HTMLMediaElement.HAVE_METADATA && Math.abs(video.currentTime - currentTime) > 0.3) {
      video.currentTime = currentTime;
    }
  }, [currentTime]);

  return (
    <>
    <video
      ref={videoRef}
      controls
      className="max-h-80 w-full rounded bg-black"
      src={videoUrl}
      onError={onError}
      onPlay={() => setPlaybackError(false)}
    />
    {playbackError && <p role="alert" className="mt-2 text-sm text-amber-200">Playback could not start. Use the video Play control to try again.</p>}
    </>
  );
}
