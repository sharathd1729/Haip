"use client";
import { useRef, useState, useEffect, useCallback } from "react";
import { Play, Pause, Volume2, VolumeX, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";

interface CallPlayerProps {
  recordingUrl: string;
  duration?: number; // seconds (for display before audio loads)
  onTimeUpdate?: (currentTime: number) => void;
  className?: string;
}

function formatTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export function CallPlayer({
  recordingUrl,
  duration: durationHint,
  onTimeUpdate,
  className,
}: CallPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(durationHint ?? 0);
  const [muted, setMuted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) { el.pause(); }
    else { el.play().catch(() => setError(true)); }
  }, [playing]);

  const handleSeekClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = audioRef.current;
    const bar = progressRef.current;
    if (!el || !bar || !duration) return;
    const rect = bar.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    el.currentTime = pct * duration;
  };

  // Expose seek method to parent via ref-style: handled in transcript turn onClick
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onLoaded = () => { setDuration(el.duration); setLoading(false); };
    const onTime = () => {
      setCurrentTime(el.currentTime);
      onTimeUpdate?.(el.currentTime);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onErr = () => { setError(true); setLoading(false); };

    el.addEventListener("loadedmetadata", onLoaded);
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("error", onErr);
    return () => {
      el.removeEventListener("loadedmetadata", onLoaded);
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("error", onErr);
    };
  }, [onTimeUpdate]);

  const pct = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className={cn(
      "flex flex-col gap-3 bg-white border border-gray-100 rounded-2xl p-4 shadow-sm",
      className
    )}>
      {/* Hidden audio element */}
      <audio ref={audioRef} src={recordingUrl} muted={muted} preload="metadata" />

      {/* Waveform progress bar */}
      <div
        ref={progressRef}
        className="relative h-10 rounded-xl bg-gray-50 border border-gray-100 cursor-pointer overflow-hidden"
        onClick={handleSeekClick}
      >
        {/* Fill */}
        <div
          className="absolute left-0 top-0 bottom-0 bg-teal-500/15 transition-none"
          style={{ width: `${pct}%` }}
        />
        {/* Fake waveform bars */}
        <div className="absolute inset-0 flex items-center gap-px px-2">
          {Array.from({ length: 64 }).map((_, i) => {
            const h = 20 + 60 * Math.abs(Math.sin(i * 0.7 + 1));
            const filled = (i / 64) * 100 < pct;
            return (
              <div
                key={i}
                className={cn(
                  "flex-1 rounded-full transition-colors",
                  filled ? "bg-teal-500" : "bg-gray-200"
                )}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
        {/* Playhead */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-teal-600 shadow-sm"
          style={{ left: `${pct}%` }}
        />
      </div>

      {/* Controls row */}
      <div className="flex items-center gap-3">
        <button
          onClick={toggle}
          disabled={loading || error}
          className="w-9 h-9 rounded-xl bg-[#0B1F3A] hover:bg-[#163458] disabled:opacity-50 text-white flex items-center justify-center transition-colors flex-shrink-0"
        >
          {loading ? (
            <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : playing ? <Pause size={16} /> : <Play size={16} />}
        </button>

        <span className="text-xs font-mono text-gray-500 tabular-nums">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>

        <div className="flex-1" />

        <button
          onClick={() => { if (audioRef.current) audioRef.current.currentTime = 0; }}
          className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors"
          title="Restart"
        >
          <RotateCcw size={14} />
        </button>

        <button
          onClick={() => { setMuted(m => !m); }}
          className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors"
          title={muted ? "Unmute" : "Mute"}
        >
          {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-500 text-center">
          Could not load recording. It may still be processing.
        </p>
      )}
    </div>
  );
}
