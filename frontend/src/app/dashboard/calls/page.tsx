"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import {
  Phone, Upload, X, ChevronRight, Filter,
  Calendar, Star, TrendingDown, TrendingUp,
  Minus, Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyCalls } from "@/components/empty-states/EmptyCalls";
import { Badge } from "@/components/ui/badge";
import { ScoreRing } from "@/components/calls/ScoreRing";
import { Skeleton } from "@/components/ui/skeleton";
import { useCallsStore } from "@/store/calls";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface CallItem {
  id: string;
  started_at: string;
  duration_seconds: number;
  direction: "inbound" | "outbound";
  guest_phone: string;
  guest_name?: string;
  agent_name?: string;
  disposition: string;
  qa_score?: number;
  sentiment?: "positive" | "negative" | "neutral";
  has_transcript: boolean;
  // Legacy compat
  call_date?: string;
  has_audio?: boolean;
  created_at?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function formatDuration(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

const DISPOSITION_BADGES: Record<string, { label: string; variant: "success" | "info" | "destructive" | "warning" | "ghost" | "secondary" }> = {
  qualified: { label: "Qualified",  variant: "info" },
  booked:    { label: "Booked",     variant: "success" },
  lost:      { label: "Lost",       variant: "destructive" },
  spam:      { label: "Spam",       variant: "ghost" },
  callback:  { label: "Callback",   variant: "warning" },
  pending:   { label: "Pending",    variant: "secondary" },
};

function SentimentIcon({ s }: { s?: string }) {
  if (s === "positive") return <TrendingUp size={13} className="text-teal-500" />;
  if (s === "negative") return <TrendingDown size={13} className="text-red-400" />;
  return <Minus size={13} className="text-gray-400" />;
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CallsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { filters, setFilters, resetFilters, wrapUpQueue, dismissWrapUp } = useCallsStore();
  const [showFilters, setShowFilters] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [search, setSearch] = useState("");

  const { data: calls = [], isLoading } = useQuery<CallItem[]>({
    queryKey: ["calls", filters],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (filters.disposition) params.disposition = filters.disposition;
      if (filters.dateFrom)    params.date_from = filters.dateFrom;
      if (filters.dateTo)      params.date_to = filters.dateTo;
      if (filters.agentId)     params.agent_id = filters.agentId;
      return api.get("/calls", { params }).then(r => r.data?.items ?? r.data ?? []);
    },
    staleTime: 30_000,
  });

  const filtered = search.trim()
    ? calls.filter(c =>
        (c.guest_phone?.includes(search)) ||
        (c.guest_name?.toLowerCase().includes(search.toLowerCase())) ||
        (c.agent_name?.toLowerCase().includes(search.toLowerCase()))
      )
    : calls;

  const hasFilters = Object.values(filters).some(Boolean);

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="px-5 py-4 border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h1 className="text-lg font-bold text-gray-900">Calls</h1>
            <p className="text-xs text-gray-400 mt-0.5">
              {filtered.length} call{filtered.length !== 1 ? "s" : ""} · Click to view full analysis
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowFilters(v => !v)}
              className={cn(
                "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors font-medium",
                hasFilters
                  ? "bg-teal-50 border-teal-200 text-teal-700"
                  : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
              )}
            >
              <Filter size={13} /> Filters {hasFilters && <span className="bg-teal-500 text-white rounded-full w-4 h-4 flex items-center justify-center text-[10px]">•</span>}
            </button>
            <button
              onClick={() => setShowUpload(true)}
              className="flex items-center gap-1.5 text-xs bg-[#0F766E] text-white px-3 py-1.5 rounded-lg font-medium hover:bg-[#0d6660] transition-colors"
            >
              <Upload size={13} /> Upload
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by guest, phone, or agent…"
            className="w-full pl-8 pr-4 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent bg-gray-50"
          />
        </div>

        {/* Filter row */}
        {showFilters && (
          <div className="mt-3 flex flex-wrap items-center gap-2 p-3 bg-gray-50 rounded-xl border border-gray-100">
            <select
              value={filters.disposition ?? ""}
              onChange={e => setFilters({ disposition: e.target.value as any })}
              className="text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-teal-500"
            >
              <option value="">All dispositions</option>
              {["pending","qualified","booked","lost","spam","callback"].map(d => (
                <option key={d} value={d} className="capitalize">{d}</option>
              ))}
            </select>

            <div className="flex items-center gap-1.5">
              <Calendar size={13} className="text-gray-400" />
              <input type="date" value={filters.dateFrom ?? ""} onChange={e => setFilters({ dateFrom: e.target.value })}
                className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-teal-500" />
              <span className="text-gray-400 text-xs">–</span>
              <input type="date" value={filters.dateTo ?? ""} onChange={e => setFilters({ dateTo: e.target.value })}
                className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-teal-500" />
            </div>

            {hasFilters && (
              <button onClick={resetFilters} className="text-xs text-red-500 hover:text-red-700 font-medium flex items-center gap-1 ml-auto">
                <X size={12} /> Clear filters
              </button>
            )}
          </div>
        )}

        {/* Wrap-up queue badges */}
        {wrapUpQueue.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {wrapUpQueue.map(callId => (
              <div key={callId} className="flex items-center gap-1.5 bg-teal-50 border border-teal-200 rounded-lg px-2.5 py-1 text-xs text-teal-700 font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-teal-500 animate-pulse" />
                Wrap-up ready
                <button onClick={() => { router.push(`/dashboard/calls/${callId}`); dismissWrapUp(callId); }}
                  className="underline hover:no-underline ml-0.5">View</button>
                <button onClick={() => dismissWrapUp(callId)} className="text-teal-400 hover:text-teal-600 ml-1"><X size={10} /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="divide-y divide-gray-50">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="px-5 py-3.5 flex items-center gap-3">
                <Skeleton className="w-9 h-9 rounded-full flex-shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <Skeleton className="h-3.5 w-48" />
                  <Skeleton className="h-3 w-32" />
                </div>
                <Skeleton className="w-10 h-10 rounded-full" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyCalls />
        ) : (
          <div className="divide-y divide-gray-50">
            {filtered.map(call => {
              const disp = DISPOSITION_BADGES[call.disposition] ?? { label: call.disposition, variant: "secondary" as const };
              const dt = call.started_at || call.created_at || "";
              const dur = call.duration_seconds;

              return (
                <button
                  key={call.id}
                  onClick={() => router.push(`/dashboard/calls/${call.id}`)}
                  className="w-full text-left px-5 py-3.5 hover:bg-gray-50/80 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    {/* Score ring or phone icon */}
                    {call.qa_score != null ? (
                      <ScoreRing score={call.qa_score} size={40} strokeWidth={4} className="flex-shrink-0" />
                    ) : (
                      <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center flex-shrink-0 group-hover:bg-blue-100 transition-colors">
                        <Phone size={16} className="text-blue-500" />
                      </div>
                    )}

                    {/* Main content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-0.5">
                        <span className="text-sm font-semibold text-gray-900 truncate">
                          {call.guest_name || call.guest_phone || "Unknown caller"}
                        </span>
                        <span className="text-[11px] text-gray-400 flex-shrink-0">{timeAgo(dt)}</span>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        {call.agent_name && (
                          <span className="text-xs text-gray-500">{call.agent_name}</span>
                        )}
                        {dur > 0 && (
                          <span className="text-xs text-gray-400">{formatDuration(dur)}</span>
                        )}
                        <Badge variant={disp.variant} className="text-[10px] py-0 h-5">
                          {disp.label}
                        </Badge>
                        <SentimentIcon s={call.sentiment} />
                        {call.has_transcript && (
                          <span className="text-[10px] text-gray-400">transcript</span>
                        )}
                      </div>
                    </div>

                    <ChevronRight size={14} className="text-gray-300 flex-shrink-0 group-hover:text-gray-500 transition-colors" />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {showUpload && (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["calls"] });
            setShowUpload(false);
          }}
        />
      )}
    </div>
  );
}

// ─── Upload modal ──────────────────────────────────────────────────────────────

type UploadTab = "file" | "transcript";

interface PipelineStep { label: string; done: boolean; active: boolean }

function UploadModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [tab, setTab] = useState<UploadTab>("file");

  // File-upload state
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [guestPhone, setGuestPhone] = useState("");
  const [agentName, setAgentName] = useState("");
  const [direction, setDirection] = useState<"inbound" | "outbound">("inbound");
  const [progress, setProgress] = useState(0);       // 0-100
  const [uploading, setUploading] = useState(false);

  // Transcript-paste state
  const [transcript, setTranscript] = useState("");
  const [agentNameTxt, setAgentNameTxt] = useState("");
  const [analyzingTxt, setAnalyzingTxt] = useState(false);

  // Done state (shared)
  const [callId, setCallId] = useState<string | null>(null);
  const [error, setError] = useState("");

  // ── File drop ──────────────────────────────────────────────────────────────
  const ACCEPTED = ".mp3,.wav,.m4a,.ogg,.aac,.flac,.webm";

  function pickFile(f: File) {
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["mp3","wav","m4a","ogg","aac","flac","webm"].includes(ext)) {
      setError("Unsupported format. Use MP3, WAV, M4A, OGG, AAC, FLAC or WebM.");
      return;
    }
    if (f.size > 200 * 1024 * 1024) {
      setError("File too large (max 200 MB).");
      return;
    }
    setError("");
    setFile(f);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  }

  // ── Upload audio ───────────────────────────────────────────────────────────
  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError("");
    setProgress(0);

    const fd = new FormData();
    fd.append("file", file);
    fd.append("guest_phone", guestPhone || "+910000000000");
    fd.append("agent_name", agentName);
    fd.append("direction", direction);

    try {
      const res = await api.post("/calls/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (evt: any) => {
          if (evt.total) setProgress(Math.round((evt.loaded / evt.total) * 100));
        },
      });
      setCallId(res.data.call_id);
      setTimeout(onSuccess, 3000);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join(", ")
        : detail ?? err?.message ?? "Upload failed — is the backend running?";
      setError(msg);
      setUploading(false);
    }
  }

  // ── Transcript paste ───────────────────────────────────────────────────────
  async function handleTranscript(e: React.FormEvent) {
    e.preventDefault();
    setAnalyzingTxt(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("transcript", transcript);
      fd.append("agent_name", agentNameTxt || "Unknown Agent");
      const res = await api.post("/analyze/transcript", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setCallId(res.data?.call_id ?? "queued");
      setTimeout(onSuccess, 2000);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "Analysis failed — check backend is running.");
      setAnalyzingTxt(false);
    }
  }

  // ── Pipeline steps (shown after upload) ───────────────────────────────────
  const steps: PipelineStep[] = [
    { label: "Recording saved",     done: !!callId, active: uploading && progress === 100 },
    { label: "Transcription queued", done: !!callId, active: !!callId },
    { label: "AI scoring queued",    done: false,    active: !!callId },
  ];

  // ── Success screen ─────────────────────────────────────────────────────────
  if (callId) {
    return (
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-8 text-center">
          <div className="w-14 h-14 rounded-full bg-teal-50 flex items-center justify-center mx-auto mb-4">
            <Phone size={24} className="text-teal-500" />
          </div>
          <h2 className="text-lg font-bold text-gray-900 mb-1">Pipeline started!</h2>
          <p className="text-sm text-gray-500 mb-6">
            Results will appear in the calls list within ~60 seconds.
          </p>
          <div className="space-y-2 text-left mb-6">
            {steps.map((s, i) => (
              <div key={i} className="flex items-center gap-3">
                <div className={cn(
                  "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0",
                  s.done ? "bg-teal-500 text-white" : "bg-gray-100 text-gray-400"
                )}>
                  {s.done ? "✓" : i + 1}
                </div>
                <span className={cn("text-sm", s.done ? "text-gray-800 font-medium" : "text-gray-400")}>
                  {s.label}
                </span>
                {s.active && !s.done && (
                  <span className="text-[10px] bg-teal-50 text-teal-600 rounded-full px-2 py-0.5 font-medium animate-pulse">
                    processing…
                  </span>
                )}
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-400">Redirecting to calls list…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div>
            <h2 className="font-semibold text-gray-900">Upload call recording</h2>
            <p className="text-xs text-gray-400 mt-0.5">MP3, WAV, M4A, OGG, AAC, FLAC · max 200 MB</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-100">
          {(["file", "transcript"] as UploadTab[]).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setError(""); }}
              className={cn(
                "flex-1 py-2.5 text-sm font-medium transition-colors",
                tab === t
                  ? "border-b-2 border-teal-500 text-teal-600"
                  : "text-gray-400 hover:text-gray-600"
              )}
            >
              {t === "file" ? "🎙 Audio file" : "📝 Paste transcript"}
            </button>
          ))}
        </div>

        {/* Error */}
        {error && (
          <div className="mx-6 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-xs">
            {error}
          </div>
        )}

        {/* ── File tab ────────────────────────────────────────────────────── */}
        {tab === "file" && (
          <form onSubmit={handleUpload} className="p-6 space-y-4">
            {/* Drop zone */}
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                "relative border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all",
                dragging ? "border-teal-400 bg-teal-50" : "border-gray-200 hover:border-teal-300 hover:bg-gray-50",
                file ? "border-teal-400 bg-teal-50/50" : ""
              )}
              onClick={() => document.getElementById("audio-file-input")?.click()}
            >
              <input
                id="audio-file-input"
                type="file"
                accept={ACCEPTED}
                className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) pickFile(f); }}
              />
              {file ? (
                <div className="flex items-center justify-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-teal-100 flex items-center justify-center flex-shrink-0">
                    <Phone size={18} className="text-teal-600" />
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-semibold text-gray-800 truncate max-w-[220px]">{file.name}</p>
                    <p className="text-xs text-gray-400">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
                  </div>
                  <button
                    type="button"
                    onClick={e => { e.stopPropagation(); setFile(null); }}
                    className="ml-auto text-gray-400 hover:text-red-500 transition-colors"
                  >
                    <X size={16} />
                  </button>
                </div>
              ) : (
                <>
                  <Upload size={28} className="mx-auto mb-2 text-gray-300" />
                  <p className="text-sm font-medium text-gray-600">Drop audio file here</p>
                  <p className="text-xs text-gray-400 mt-1">or click to browse</p>
                </>
              )}
            </div>

            {/* Upload progress bar */}
            {uploading && (
              <div>
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>{progress < 100 ? "Uploading…" : "Processing…"}</span>
                  <span>{progress}%</span>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-1.5">
                  <div
                    className="bg-teal-500 h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}

            {/* Fields */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Guest phone</label>
                <input
                  value={guestPhone}
                  onChange={e => setGuestPhone(e.target.value)}
                  placeholder="+91 98765 43210"
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Agent name</label>
                <input
                  value={agentName}
                  onChange={e => setAgentName(e.target.value)}
                  placeholder="Ravi Kumar"
                  className="w-full px-3 py-2 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Call direction</label>
              <div className="flex gap-2">
                {(["inbound", "outbound"] as const).map(d => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDirection(d)}
                    className={cn(
                      "flex-1 py-2 rounded-xl text-xs font-medium border transition-colors capitalize",
                      direction === d
                        ? "bg-teal-50 border-teal-400 text-teal-700"
                        : "border-gray-200 text-gray-500 hover:bg-gray-50"
                    )}
                  >
                    {d === "inbound" ? "↙ Inbound" : "↗ Outbound"}
                  </button>
                ))}
              </div>
            </div>

            <button
              type="submit"
              disabled={!file || uploading}
              className="w-full py-2.5 bg-[#0F766E] text-white font-semibold rounded-xl text-sm hover:bg-[#0d6660] disabled:opacity-40 transition-colors"
            >
              {uploading ? "Uploading…" : "Upload & analyze →"}
            </button>
          </form>
        )}

        {/* ── Transcript tab ───────────────────────────────────────────────── */}
        {tab === "transcript" && (
          <form onSubmit={handleTranscript} className="p-6 space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Agent name</label>
              <input
                value={agentNameTxt}
                onChange={e => setAgentNameTxt(e.target.value)}
                placeholder="Ravi Kumar"
                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Paste transcript</label>
              <textarea
                required
                value={transcript}
                onChange={e => setTranscript(e.target.value)}
                rows={8}
                placeholder={"Agent: Good morning, HAIP Villa. How can I help?\nGuest: Hi, I'd like to book a room for 3 nights…"}
                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
            <button
              type="submit"
              disabled={analyzingTxt}
              className="w-full py-2.5 bg-teal-500 text-white font-semibold rounded-xl text-sm hover:bg-teal-600 disabled:opacity-50 transition-colors"
            >
              {analyzingTxt ? "Analyzing…" : "Analyze with AI →"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
