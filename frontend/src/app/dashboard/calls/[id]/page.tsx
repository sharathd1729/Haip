"use client";
import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  ArrowLeft, Phone, Clock, User, ChevronDown,
  CheckCircle2, AlertCircle, Save, Loader2, ExternalLink, Play,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { CallPlayer } from "@/components/calls/CallPlayer";
import { TranscriptTurn } from "@/components/calls/TranscriptTurn";
import { ScoreRing } from "@/components/calls/ScoreRing";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";

// ─── Types ─────────────────────────────────────────────────────────────────────

interface Turn {
  speaker: string;
  t0: number;
  t1: number;
  text: string;
}

interface CriterionScore {
  criterion: string;
  score: number;
  max_score: number;
  evidence: string;
  evidence_spans?: { start: number; end: number; label?: string; sentiment?: "positive" | "negative" | "neutral" }[];
}

interface CallDetail {
  id: string;
  started_at: string;
  duration_seconds: number;
  direction: "inbound" | "outbound";
  recording_url?: string | null;
  guest_phone: string;
  guest_name?: string;
  agent_name?: string;
  disposition: string;
  transcription_status?: string;
  ai_score_status?: string;
  ivr_provider?: string;
  transcript?: { turns: Turn[] } | null;
  score?: {
    total_score: number;
    max_score: number;
    confidence: number;
    criteria: CriterionScore[];
    summary?: string;
    agent_strengths?: string[];
    agent_growth_areas?: string[];
    missed_revenue?: number;
    suggested_disposition?: string;
    next_action?: string;
    ai_summary?: string;
  };
}

const DISPOSITION_OPTIONS = [
  { value: "pending",   label: "Pending",   color: "bg-gray-100 text-gray-600" },
  { value: "qualified", label: "Qualified",  color: "bg-blue-100 text-blue-700" },
  { value: "booked",    label: "Booked",     color: "bg-teal-100 text-teal-700" },
  { value: "lost",      label: "Lost",       color: "bg-red-100 text-red-600" },
  { value: "spam",      label: "Spam",       color: "bg-gray-100 text-gray-400" },
  { value: "callback",  label: "Callback",   color: "bg-amber-100 text-amber-700" },
];

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}
function formatDuration(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}m ${sec}s`;
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function CallDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();

  const [playheadTime, setPlayheadTime] = useState(0);
  const [disposition, setDisposition] = useState("");
  const [wrapUpNotes, setWrapUpNotes] = useState("");
  const [showAllCriteria, setShowAllCriteria] = useState(false);
  const [processing, setProcessing] = useState(false);

  const isPipelineRunning = (call: CallDetail | undefined) =>
    call && ["queued", "pending", "processing"].includes(call.transcription_status ?? "");

  const { data: call, isLoading, error } = useQuery<CallDetail>({
    queryKey: ["call", id],
    queryFn: () => api.get(`/calls/${id}`).then(r => r.data),
    staleTime: 0,          // always re-fetch on mount — score can change after pipeline runs
    refetchOnMount: true,
    // Poll every 4s while transcription or QA scoring is in progress
    refetchInterval: (query: any) => {
      const data = query.state?.data;
      if (!data) return false;
      if (data.transcription_status === "processing") return 4000;
      if (data.ai_score_status === "processing") return 4000;
      return false;
    },
  });

  // Populate disposition + summary once data arrives (replaces deprecated onSuccess)
  useEffect(() => {
    if (!call) return;
    if (!disposition) setDisposition(call.disposition ?? "pending");
    if (!wrapUpNotes && call.score?.ai_summary) setWrapUpNotes(call.score.ai_summary);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call?.id, call?.score?.ai_summary, call?.disposition]);

  // Sync processing trigger (for when Celery worker isn't running)
  const processMutation = useMutation({
    mutationFn: () => api.post(`/calls/${id}/process`),
    onMutate: () => setProcessing(true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["call", id] });
      queryClient.invalidateQueries({ queryKey: ["calls"] });
      setProcessing(false);
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Processing failed";
      toast({ variant: "error", title: "Processing error", description: msg });
      setProcessing(false);
    },
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      api.post(`/calls/${id}/wrap-up`, {
        disposition,
        notes: wrapUpNotes,
        next_action: call?.score?.next_action,
      }),
    onSuccess: () => {
      toast({ variant: "success", title: "Wrap-up saved", description: "Call disposition and notes updated." });
      queryClient.invalidateQueries({ queryKey: ["call", id] });
      queryClient.invalidateQueries({ queryKey: ["calls"] });
    },
    onError: () => {
      toast({ variant: "error", title: "Save failed", description: "Please try again." });
    },
  });

  const activeIdx = call?.transcript?.turns?.findLastIndex(t => t.t0 <= playheadTime) ?? -1;

  if (isLoading) return <CallDetailSkeleton />;
  if (error || !call) {
    const status = (error as any)?.response?.status;
    const msg = status === 401
      ? "Session expired — please sign out and sign in again."
      : status === 404
      ? "Call not found or you don't have access."
      : "Failed to load call. Check that the backend is running.";
    return (
      <div className="p-8 text-center">
        <AlertCircle size={40} className="text-red-400 mx-auto mb-3" />
        <p className="text-gray-500">{msg}</p>
        <button onClick={() => router.back()} className="mt-4 text-teal-600 text-sm font-medium">← Go back</button>
      </div>
    );
  }

  const dispOpt = DISPOSITION_OPTIONS.find(d => d.value === disposition) ?? DISPOSITION_OPTIONS[0];
  const criteria = call.score?.criteria ?? [];
  const visibleCriteria = showAllCriteria ? criteria : criteria.slice(0, 5);

  return (
    <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link href="/dashboard/calls" className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-700 transition-colors">
          <ArrowLeft size={16} /> Back to calls
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-bold text-gray-900 truncate">
            Call with {call.guest_name || call.guest_phone}
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">{formatDate(call.started_at)}</p>
        </div>

        {/* Meta badges */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <Badge variant={call.direction === "inbound" ? "info" : "secondary"} className="capitalize">
            <Phone size={11} /> {call.direction}
          </Badge>
          <Badge variant="ghost">
            <Clock size={11} /> {formatDuration(call.duration_seconds)}
          </Badge>
          {call.agent_name && (
            <Badge variant="outline">
              <User size={11} /> {call.agent_name}
            </Badge>
          )}
        </div>
      </div>

      {/* Pipeline status banner — transcription not done */}
      {call.transcription_status && call.transcription_status !== "done" && (
        <div className={cn(
          "rounded-2xl px-5 py-3.5 flex items-center justify-between gap-4",
          call.transcription_status === "processing"
            ? "bg-blue-50 border border-blue-200"
            : call.transcription_status === "failed"
            ? "bg-red-50 border border-red-200"
            : "bg-amber-50 border border-amber-200"
        )}>
          <div className="flex items-center gap-3">
            {call.transcription_status === "processing" ? (
              <Loader2 size={16} className="text-blue-500 animate-spin flex-shrink-0" />
            ) : call.transcription_status === "failed" ? (
              <AlertCircle size={16} className="text-red-500 flex-shrink-0" />
            ) : (
              <AlertCircle size={16} className="text-amber-500 flex-shrink-0" />
            )}
            <div>
              <p className={cn("text-sm font-semibold",
                call.transcription_status === "processing" ? "text-blue-800"
                : call.transcription_status === "failed" ? "text-red-800"
                : "text-amber-800"
              )}>
                {call.transcription_status === "processing" ? "Transcription in progress…"
                  : call.transcription_status === "queued" ? "Waiting for Celery worker"
                  : call.transcription_status === "failed" ? "Transcription failed"
                  : `Transcription ${call.transcription_status}`}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {call.transcription_status === "processing"
                  ? "This page will refresh automatically."
                  : "Click \"Process now\" to run the full pipeline directly (no Celery needed)."}
              </p>
            </div>
          </div>
          {["queued", "pending", "failed"].includes(call.transcription_status ?? "") && (
            <button
              onClick={() => processMutation.mutate()}
              disabled={processing}
              className="flex items-center gap-2 px-4 py-2 bg-[#0B1F3A] text-white text-xs font-semibold rounded-xl hover:bg-[#163458] disabled:opacity-50 transition-colors flex-shrink-0"
            >
              {processing
                ? <><Loader2 size={13} className="animate-spin" /> Processing…</>
                : <><Play size={13} /> Process now</>}
            </button>
          )}
        </div>
      )}

      {/* Pipeline status banner — transcription done but QA scoring not done */}
      {call.transcription_status === "done" && call.ai_score_status && call.ai_score_status !== "done" && (
        <div className={cn(
          "rounded-2xl px-5 py-3.5 flex items-center justify-between gap-4",
          call.ai_score_status === "processing"
            ? "bg-blue-50 border border-blue-200"
            : call.ai_score_status === "failed"
            ? "bg-red-50 border border-red-200"
            : "bg-amber-50 border border-amber-200"
        )}>
          <div className="flex items-center gap-3">
            {call.ai_score_status === "processing" ? (
              <Loader2 size={16} className="text-blue-500 animate-spin flex-shrink-0" />
            ) : call.ai_score_status === "failed" ? (
              <AlertCircle size={16} className="text-red-500 flex-shrink-0" />
            ) : (
              <AlertCircle size={16} className="text-amber-500 flex-shrink-0" />
            )}
            <div>
              <p className={cn("text-sm font-semibold",
                call.ai_score_status === "processing" ? "text-blue-800"
                : call.ai_score_status === "failed" ? "text-red-800"
                : "text-amber-800"
              )}>
                {call.ai_score_status === "processing" ? "QA analysis in progress…"
                  : call.ai_score_status === "failed" ? "QA scoring failed — click to retry"
                  : "QA scoring not started yet"}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {call.ai_score_status === "processing"
                  ? "This page will refresh automatically."
                  : "Transcript is ready. Click \"Run QA\" to score this call now."}
              </p>
            </div>
          </div>
          {call.ai_score_status !== "processing" && (
            <button
              onClick={() => processMutation.mutate()}
              disabled={processing}
              className="flex items-center gap-2 px-4 py-2 bg-[#0B1F3A] text-white text-xs font-semibold rounded-xl hover:bg-[#163458] disabled:opacity-50 transition-colors flex-shrink-0"
            >
              {processing
                ? <><Loader2 size={13} className="animate-spin" /> Running…</>
                : <><Play size={13} /> Run QA</>}
            </button>
          )}
        </div>
      )}

      <div className="grid grid-cols-12 gap-6">
        {/* ── Left: audio + transcript ──────────────────────────────────────── */}
        <div className="col-span-12 lg:col-span-7 space-y-5">
          {/* Audio player */}
          {call.recording_url ? (
            <CallPlayer
              recordingUrl={
                // Local files come back as /api/v1/calls/{id}/recording (relative path).
                // Prefix with the backend base URL and append the session token so
                // the <audio> element can authenticate without Authorization headers.
                call.recording_url.startsWith("/")
                  ? (() => {
                      const base = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1")
                        .replace(/\/api\/v1$/, "");
                      const tok = (session as any)?.accessToken ?? "demo";
                      return `${base}${call.recording_url}?token=${encodeURIComponent(tok)}`;
                    })()
                  : call.recording_url
              }
              duration={call.duration_seconds}
              onTimeUpdate={setPlayheadTime}
            />
          ) : (
            <div className="bg-gray-50 border border-dashed border-gray-200 rounded-2xl h-24 flex items-center justify-center">
              <p className="text-sm text-gray-400">Recording not yet available</p>
            </div>
          )}

          {/* Transcript */}
          <div className="bg-white border border-gray-100 rounded-2xl shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-gray-50 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900">Transcript</h2>
              {call.guest_phone && (
                <Link
                  href={`/dashboard/guests?phone=${encodeURIComponent(call.guest_phone)}`}
                  className="text-xs text-teal-600 hover:text-teal-700 flex items-center gap-1 font-medium"
                >
                  View guest profile <ExternalLink size={11} />
                </Link>
              )}
            </div>
            <div className="p-4 space-y-2 max-h-[520px] overflow-y-auto">
              {call.transcript?.turns && call.transcript.turns.length > 0 ? (
                call.transcript.turns.map((turn, idx) => {
                  const scoreForTurn = criteria.flatMap(c => c.evidence_spans ?? []);
                  return (
                    <TranscriptTurn
                      key={idx}
                      speaker={turn.speaker}
                      text={turn.text}
                      t0={turn.t0}
                      t1={turn.t1}
                      evidenceSpans={scoreForTurn}
                      isActive={idx === activeIdx}
                      onClick={(t) => {
                        const audio = document.querySelector("audio");
                        if (audio) { audio.currentTime = t; audio.play().catch(() => {}); }
                      }}
                    />
                  );
                })
              ) : (
                <div className="text-center py-10">
                  {call.transcription_status === "processing" ? (
                    <>
                      <Loader2 size={20} className="text-blue-300 mx-auto mb-2 animate-spin" />
                      <p className="text-sm text-gray-400">Transcription in progress…</p>
                    </>
                  ) : call.transcription_status === "queued" ? (
                    <>
                      <Clock size={20} className="text-amber-300 mx-auto mb-2" />
                      <p className="text-sm text-gray-400">Waiting for processing — click "Process now" above</p>
                    </>
                  ) : (
                    <p className="text-sm text-gray-400">No transcript available</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Right: score + wrap-up ────────────────────────────────────────── */}
        <div className="col-span-12 lg:col-span-5 space-y-5">
          {/* QA Score card */}
          {call.score ? (
            <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-5">
              <div className="flex items-center gap-4 mb-5">
                <ScoreRing score={(call.score.total_score / call.score.max_score) * 100} size={72} />
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">QA Score</h2>
                  <p className="text-2xl font-black text-gray-900 mt-0.5">
                    {call.score.total_score}
                    <span className="text-base font-normal text-gray-400">/{call.score.max_score}</span>
                  </p>
                  {call.score.confidence && (
                    <p className="text-xs text-gray-400 mt-0.5">
                      Confidence: {Math.round(call.score.confidence * 100)}%
                    </p>
                  )}
                </div>
              </div>

              {/* Criteria breakdown */}
              <div className="space-y-2.5">
                {visibleCriteria.map((c, i) => {
                  const pct = Math.round((c.score / c.max_score) * 100);
                  return (
                    <div key={i}>
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="text-gray-600 font-medium capitalize">{c.criterion.replace(/_/g, " ")}</span>
                        <span className="text-gray-500 font-mono">{c.score}/{c.max_score}</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className={cn(
                            "h-full rounded-full transition-all",
                            pct >= 80 ? "bg-teal-500" : pct >= 50 ? "bg-amber-400" : "bg-red-400"
                          )}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      {c.evidence && (
                        <p className="text-[11px] text-gray-400 mt-0.5 italic line-clamp-1">{c.evidence}</p>
                      )}
                    </div>
                  );
                })}
              </div>

              {criteria.length > 5 && (
                <button
                  onClick={() => setShowAllCriteria(v => !v)}
                  className="mt-3 text-xs text-teal-600 hover:text-teal-700 font-medium flex items-center gap-1"
                >
                  {showAllCriteria ? "Show less" : `+${criteria.length - 5} more criteria`}
                  <ChevronDown size={12} className={cn("transition-transform", showAllCriteria && "rotate-180")} />
                </button>
              )}

              {/* Strengths & growth areas */}
              {(call.score.agent_strengths?.length || call.score.agent_growth_areas?.length) && (
                <div className="mt-4 pt-4 border-t border-gray-50 grid grid-cols-2 gap-3">
                  {call.score.agent_strengths?.length ? (
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-teal-600 mb-1.5">Strengths</p>
                      <ul className="space-y-1">
                        {call.score.agent_strengths.slice(0, 3).map((s, i) => (
                          <li key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
                            <CheckCircle2 size={11} className="text-teal-400 mt-0.5 flex-shrink-0" /> {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {call.score.agent_growth_areas?.length ? (
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-wider text-amber-600 mb-1.5">Improve</p>
                      <ul className="space-y-1">
                        {call.score.agent_growth_areas.slice(0, 3).map((s, i) => (
                          <li key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
                            <AlertCircle size={11} className="text-amber-400 mt-0.5 flex-shrink-0" /> {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white border border-dashed border-gray-200 rounded-2xl p-6 text-center">
              <Loader2 size={24} className="text-gray-300 mx-auto mb-2 animate-spin" />
              <p className="text-sm text-gray-400">QA analysis in progress…</p>
            </div>
          )}

          {/* Wrap-up panel */}
          <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Wrap-up</h2>

            {/* Disposition */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Disposition
              </label>
              <div className="grid grid-cols-3 gap-1.5">
                {DISPOSITION_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => setDisposition(opt.value)}
                    className={cn(
                      "py-2 px-2 rounded-xl text-xs font-semibold border transition-all",
                      disposition === opt.value
                        ? `${opt.color} border-current/30 ring-2 ring-current/20`
                        : "bg-gray-50 border-gray-100 text-gray-500 hover:bg-gray-100"
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* AI summary */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                Summary / notes
              </label>
              <textarea
                value={wrapUpNotes}
                onChange={e => setWrapUpNotes(e.target.value)}
                rows={4}
                placeholder="AI summary will appear here after analysis completes. You can also add manual notes."
                className="w-full px-3 py-2.5 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-shadow resize-none text-gray-700 placeholder:text-gray-300"
              />
            </div>

            {/* Suggested next action */}
            {call.score?.next_action && (
              <div className="mb-4 p-3 bg-teal-50 border border-teal-100 rounded-xl">
                <p className="text-xs font-semibold text-teal-700 mb-1">Suggested next action</p>
                <p className="text-sm text-teal-800">{call.score.next_action}</p>
              </div>
            )}

            {/* Missed revenue */}
            {call.score?.missed_revenue && call.score.missed_revenue > 0 && (
              <div className="mb-4 p-3 bg-red-50 border border-red-100 rounded-xl">
                <p className="text-xs font-semibold text-red-600 mb-0.5">Potential missed revenue</p>
                <p className="text-base font-bold text-red-700">
                  ₹{call.score.missed_revenue.toLocaleString("en-IN")}
                </p>
              </div>
            )}

            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="w-full py-2.5 bg-[#0B1F3A] hover:bg-[#163458] disabled:opacity-60 text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2"
            >
              {saveMutation.isPending ? (
                <><Loader2 size={14} className="animate-spin" /> Saving…</>
              ) : (
                <><Save size={14} /> Save wrap-up</>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CallDetailSkeleton() {
  return (
    <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
      <div className="flex items-center gap-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-6 w-48" />
      </div>
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-7 space-y-5">
          <Skeleton className="h-24 w-full rounded-2xl" />
          <Skeleton className="h-[400px] w-full rounded-2xl" />
        </div>
        <div className="col-span-5 space-y-5">
          <Skeleton className="h-64 w-full rounded-2xl" />
          <Skeleton className="h-80 w-full rounded-2xl" />
        </div>
      </div>
    </div>
  );
}
