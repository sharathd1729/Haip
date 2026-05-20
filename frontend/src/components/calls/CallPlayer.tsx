"use client";
import { useRef, useState, useEffect, useCallback } from "react";
import { Play, Pause, Volume2, VolumeX, RotateCcw, SkipBack, SkipForward } from "lucide-react";
import { cn } from "@/lib/utils";

interface CallPlayerProps {
  recordingUrl: string;
  duration?: number;
  onTimeUpdate?: (currentTime: number) => void;
  className?: string;
}

const SPEEDS = [1, 1.25, 1.5, 1.75, 2];
const SPEED_KEY = "haip.callPlayer.speed";

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
  const audioRef  = useRef<HTMLAudioElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [playing,     setPlaying]     = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration,    setDuration]    = useState(durationHint ?? 0);
  const [muted,       setMuted]       = useState(false);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(false);
  const [focused,     setFocused]     = useState(false);

  // C10: persisted playback speed
  const [speed, setSpeed] = useState<number>(() => {
    if (typeof window === "undefined") return 1;
    return parseFloat(localStorage.getItem(SPEED_KEY) ?? "1") || 1;
  });

  const changeSpeed = (s: number) => {
    setSpeed(s);
    localStorage.setItem(SPEED_KEY, String(s));
    if (audioRef.current) audioRef.current.playbackRate = s;
  };

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) { el.pause(); }
    else { el.play().catch(() => setError(true)); }
  }, [playing]);

  // C10: skip ±seconds
  const skip = useCallback((secs: number) => {
    const el = audioRef.current;
    if (!el || !duration) return;
    el.currentTime = Math.max(0, Math.min(duration, el.currentTime + secs));
  }, [duration]);

  const handleSeekClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const el  = audioRef.current;
    const bar = progressRef.current;
    if (!el || !bar || !duration) return;
    const rect = bar.getBoundingClientRect();
    const pct  = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    el.currentTime = pct * duration;
  };

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const onLoaded = () => { setDuration(el.duration); setLoading(false); el.playbackRate = speed; };
    const onTime   = () => { setCurrentTime(el.currentTime); onTimeUpdate?.(el.currentTime); };
    const onPlay   = () => setPlaying(true);
    const onPause  = () => setPlaying(false);
    const onErr    = () => { setError(true); setLoading(false); };

    el.addEventListener("loadedmetadata", onLoaded);
    el.addEventListener("timeupdate",     onTime);
    el.addEventListener("play",           onPlay);
    el.addEventListener("pause",          onPause);
    el.addEventListener("error",          onErr);
    return () => {
      el.removeEventListener("loadedmetadata", onLoaded);
      el.removeEventListener("timeupdate",     onTime);
      el.removeEventListener("play",           onPlay);
      el.removeEventListener("pause",          onPause);
      el.removeEventListener("error",          onErr);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onTimeUpdate]);

  // C10: keyboard shortcuts (gated to when player is focused)
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (!focused) return;
      if (e.key === " " || e.key === "k")         { e.preventDefault(); toggle(); }
      else if (e.key === "ArrowLeft"  || e.key === "j") { e.preventDefault(); skip(-5); }
      else if (e.key === "ArrowRight" || e.key === "l") { e.preventDefault(); skip(5); }
      else if (e.key === "j" && e.shiftKey)        { e.preventDefault(); skip(-10); }
      else if (e.key === "l" && e.shiftKey)        { e.preventDefault(); skip(10); }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [focused, toggle, skip]);

  const pct = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className={cn(
        "flex flex-col gap-3 bg-white border border-gray-100 rounded-2xl p-4 shadow-sm outline-none",
        focused && "ring-2 ring-teal-300",
        className
      )}
    >
      <audio ref={audioRef} src={recordingUrl} muted={muted} preload="metadata" />

      {/* Waveform / progress bar */}
      <div
        ref={progressRef}
        className="relative h-10 rounded-xl bg-gray-50 border border-gray-100 cursor-pointer overflow-hidden"
        onClick={handleSeekClick}
      >
        <div
          className="absolute left-0 top-0 bottom-0 bg-teal-500/15 transition-none"
          style={{ width: `${pct}%` }}
        />
        <div className="absolute inset-0 flex items-center gap-px px-2">
          {Array.from({ length: 64 }).map((_, i) => {
            const h      = 20 + 60 * Math.abs(Math.sin(i * 0.7 + 1));
            const filled = (i / 64) * 100 < pct;
            return (
              <div
                key={i}
                className={cn("flex-1 rounded-full transition-colors", filled ? "bg-teal-500" : "bg-gray-200")}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-teal-600 shadow-sm"
          style={{ left: `${pct}%` }}
        />
      </div>

      {/* Controls row */}
      <div className="flex items-center gap-2">
        {/* C10: Skip back 10s */}
        <button
          onClick={() => skip(-10)}
          disabled={loading || error}
          title="Skip back 10s (J)"
          className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors disabled:opacity-40"
        >
          <SkipBack size={14} />
        </button>

        {/* Play / Pause */}
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

        {/* C10: Skip forward 10s */}
        <button
          onClick={() => skip(10)}
          disabled={loading || error}
          title="Skip forward 10s (L)"
          className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors disabled:opacity-40"
        >
          <SkipForward size={14} />
        </button>

        <span className="text-xs font-mono text-gray-500 tabular-nums ml-1">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>

        <div className="flex-1" />

        {/* C10: Speed selector */}
        <div className="flex items-center gap-0.5 bg-gray-100 rounded-lg p-0.5">
          {SPEEDS.map(s => (
            <button
              key={s}
              onClick={() => changeSpeed(s)}
              className={cn(
                "px-1.5 py-0.5 rounded text-[11px] font-medium transition-colors",
                speed === s
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              {s}×
            </button>
          ))}
        </div>

        <button
          onClick={() => { if (audioRef.current) audioRef.current.currentTime = 0; }}
          className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors"
          title="Restart"
        >
          <RotateCcw size={14} />
        </button>

        <button
          onClick={() => setMuted(m => !m)}
          className="w-8 h-8 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex items-center justify-center transition-colors"
          title={muted ? "Unmute" : "Mute"}
        >
          {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
        </button>
      </div>

      {focused && (
        <p className="text-[10px] text-gray-400 text-center">
          Space/K = play · ← → = ±5s · J/L = ±10s
        </p>
      )}

      {error && (
        <p className="text-xs text-red-500 text-center">
          Could not load recording. It may still be processing.
        </p>
      )}
    </div>
  );
}
