"use client";
import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  ArrowLeft, Phone, Clock, User, ChevronDown, ChevronRight,
  CheckCircle2, AlertCircle, Save, Loader2, ExternalLink, Play, Copy, Star, BookmarkIcon, MessageSquare, X,
  Heart, TrendingUp, Target, AlertTriangle, Globe, Layers,
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

interface Layer2 {
  occasion?: string | null;
  budget_signal?: string | null;
  decision_stage?: string | null;
  competitor_mentioned?: string | null;
  conversion_probability?: number | null;
  lost_reason?: string | null;
  sentiment?: string | null;
  detected_language?: string | null;
  is_code_mixed?: boolean;
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
  layer2?: Layer2 | null;
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
  recommended_action?: {
    type: string;
    label: string;
    target_field: string;
    target: string;
    target_conversation_id?: string | null;
  } | null;
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
  // C3: track which criteria are expanded (multiple can be open simultaneously)
  const [expandedCriteria, setExpandedCriteria] = useState<Set<number>>(new Set());
  // C8: per-turn bookmarks (stored locally, keyed by turn index)
  const [bookmarks, setBookmarks] = useState<Set<number>>(new Set());
  // C7: per-turn coaching notes (local, keyed by turn index)
  const [coachingNotes, setCoachingNotes] = useState<Record<number, string>>({});
  const [editingNote, setEditingNote] = useState<number | null>(null);
  const [noteInput, setNoteInput] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);

  const toggleBookmark = (idx: number) =>
    setBookmarks(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });

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

  // M5+ WS1/WS3: reuses the existing approve-and-queue endpoint
  // (conversations.py::approve_ai_draft) rather than a new one.
  const approveAndSendMutation = useMutation({
    mutationFn: ({ conversationId, messageId }: { conversationId: string; messageId: string }) =>
      api.post(`/conversations/${conversationId}/messages/${messageId}/approve`),
    onSuccess: () => {
      toast({ variant: "success", title: "Draft sent", description: "The WhatsApp reply is on its way." });
      queryClient.invalidateQueries({ queryKey: ["call", id] });
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Could not send the draft";
      toast({ variant: "error", title: "Send failed", description: msg });
    },
  });

  // C1: correct active-turn calculation — last turn whose range contains playheadTime
  const activeIdx = call?.transcript?.turns?.reduce<number>((best, t, i) => {
    // t0 is turn start in seconds; prefer the turn that has started and not yet ended
    if (t.t0 <= playheadTime && (t.t1 === undefined || playheadTime < t.t1)) return i;
    return best;
  }, -1) ?? -1;

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
              className="flex items-center gap-2 px-4 py-2 bg-[#0F766E] text-white text-xs font-semibold rounded-xl hover:bg-[#0d6660] disabled:opacity-50 transition-colors flex-shrink-0"
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
              className="flex items-center gap-2 px-4 py-2 bg-[#0F766E] text-white text-xs font-semibold rounded-xl hover:bg-[#0d6660] disabled:opacity-50 transition-colors flex-shrink-0"
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
          <div className="haip-card overflow-hidden">
            <div className="haip-card-head">
              <h2 className="haip-card-title">Transcript</h2>
              {call.guest_phone && (
                <Link
                  href={`/dashboard/guests?phone=${encodeURIComponent(call.guest_phone)}`}
                  className="text-xs text-teal-600 hover:text-teal-700 flex items-center gap-1 font-medium"
                >
                  View guest profile <ExternalLink size={11} />
                </Link>
              )}
            </div>
            <div ref={transcriptRef} className="p-4 space-y-2 max-h-[520px] overflow-y-auto">
              {call.transcript?.turns && call.transcript.turns.length > 0 ? (
                call.transcript.turns.map((turn, idx) => {
                  const scoreForTurn = criteria.flatMap(c => c.evidence_spans ?? []);
                  const isActive = idx === activeIdx;
                  const isBookmarked = bookmarks.has(idx);
                  const hasNote = !!coachingNotes[idx];
                  const isEditingThis = editingNote === idx;
                  return (
                    <div key={idx} className="relative group/turn">
                      <div className="flex items-start gap-1">
                        {/* C8: bookmark star button */}
                        <button
                          onClick={() => toggleBookmark(idx)}
                          title={isBookmarked ? "Remove bookmark" : "Bookmark this moment"}
                          className={cn(
                            "flex-shrink-0 mt-2 w-5 h-5 flex items-center justify-center rounded transition-colors",
                            isBookmarked
                              ? "text-amber-400"
                              : "text-transparent group-hover/turn:text-gray-300 hover:!text-amber-400"
                          )}
                        >
                          <Star size={13} className={isBookmarked ? "fill-amber-400" : ""} />
                        </button>
                        <div className="flex-1 min-w-0">
                          <TranscriptTurn
                            speaker={turn.speaker}
                            text={turn.text}
                            t0={turn.t0}
                            t1={turn.t1}
                            evidenceSpans={scoreForTurn}
                            isActive={isActive}
                            onClick={(t) => {
                              const audio = document.querySelector("audio") as HTMLAudioElement | null;
                              if (!audio) return;
                              if (isActive && !audio.paused) {
                                audio.pause();
                              } else {
                                audio.currentTime = t;
                                audio.play().catch(() => {});
                              }
                            }}
                          />
                        </div>
                        {/* C7: coaching comment button */}
                        <button
                          onClick={() => {
                            if (isEditingThis) {
                              setEditingNote(null);
                            } else {
                              setEditingNote(idx);
                              setNoteInput(coachingNotes[idx] ?? "");
                            }
                          }}
                          title={hasNote ? "Edit coaching note" : "Add coaching note"}
                          className={cn(
                            "flex-shrink-0 mt-2 w-5 h-5 flex items-center justify-center rounded transition-colors",
                            hasNote
                              ? "text-blue-400"
                              : "text-transparent group-hover/turn:text-gray-300 hover:!text-blue-400"
                          )}
                        >
                          <MessageSquare size={13} className={hasNote ? "fill-blue-100" : ""} />
                        </button>
                      </div>

                      {/* C7: coaching note display */}
                      {hasNote && !isEditingThis && (
                        <div className="ml-6 mt-1 flex items-start gap-2 px-3 py-2 bg-blue-50 border border-blue-100 rounded-xl">
                          <MessageSquare size={11} className="text-blue-400 mt-0.5 flex-shrink-0" />
                          <p className="flex-1 text-xs text-blue-800">{coachingNotes[idx]}</p>
                          <button
                            onClick={() => {
                              setEditingNote(idx);
                              setNoteInput(coachingNotes[idx] ?? "");
                            }}
                            className="text-blue-300 hover:text-blue-600 text-[10px]">edit</button>
                          <button
                            onClick={() => setCoachingNotes(prev => { const n = { ...prev }; delete n[idx]; return n; })}
                            className="text-blue-200 hover:text-red-400 transition-colors"
                          >
                            <X size={10} />
                          </button>
                        </div>
                      )}

                      {/* C7: coaching note editor */}
                      {isEditingThis && (
                        <div className="ml-6 mt-1 flex flex-col gap-1.5">
                          <textarea
                            autoFocus
                            value={noteInput}
                            onChange={e => setNoteInput(e.target.value)}
                            placeholder="Add a coaching note for this turn…"
                            rows={2}
                            className="w-full text-xs px-3 py-2 border border-blue-200 rounded-xl bg-blue-50 text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-300 resize-none"
                            onKeyDown={e => {
                              if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                if (noteInput.trim()) {
                                  setCoachingNotes(prev => ({ ...prev, [idx]: noteInput.trim() }));
                                } else {
                                  setCoachingNotes(prev => { const n = { ...prev }; delete n[idx]; return n; });
                                }
                                setEditingNote(null);
                              } else if (e.key === "Escape") {
                                setEditingNote(null);
                              }
                            }}
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={() => {
                                if (noteInput.trim()) {
                                  setCoachingNotes(prev => ({ ...prev, [idx]: noteInput.trim() }));
                                } else {
                                  setCoachingNotes(prev => { const n = { ...prev }; delete n[idx]; return n; });
                                }
                                setEditingNote(null);
                              }}
                              className="text-[11px] font-medium px-2.5 py-1 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingNote(null)}
                              className="text-[11px] text-gray-400 hover:text-gray-600 px-2"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
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
            <div className="haip-card p-5">
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

              {/* Criteria breakdown — C3: click to expand evidence */}
              <div className="space-y-2">
                {visibleCriteria.map((c, i) => {
                  const pct = Math.round((c.score / c.max_score) * 100);
                  const isExpanded = expandedCriteria.has(i);
                  return (
                    <div key={i} className="rounded-xl border border-gray-100 overflow-hidden">
                      <button
                        className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-gray-50 transition-colors"
                        onClick={() => setExpandedCriteria(prev => {
                          const next = new Set(prev);
                          isExpanded ? next.delete(i) : next.add(i);
                          return next;
                        })}
                      >
                        {isExpanded
                          ? <ChevronDown size={12} className="text-gray-400 flex-shrink-0" />
                          : <ChevronRight size={12} className="text-gray-400 flex-shrink-0" />}
                        <span className="text-xs text-gray-600 font-medium capitalize flex-1">{c.criterion.replace(/_/g, " ")}</span>
                        <span className="text-xs text-gray-500 font-mono flex-shrink-0">{c.score}/{c.max_score}</span>
                      </button>
                      <div className="px-3 pb-2">
                        <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden mb-1">
                          <div
                            className={cn("h-full rounded-full", pct >= 80 ? "bg-teal-500" : pct >= 50 ? "bg-amber-400" : "bg-red-400")}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        {/* Collapsed: one-line preview */}
                        {c.evidence && !isExpanded && (
                          <p className="text-[11px] text-gray-400 italic line-clamp-1">{c.evidence}</p>
                        )}
                      </div>
                      {/* Expanded: full evidence + copy */}
                      {isExpanded && c.evidence && (
                        <div className="px-3 pb-3 border-t border-gray-50 pt-2">
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-xs text-gray-600 leading-relaxed flex-1">{c.evidence}</p>
                            <button
                              onClick={() => navigator.clipboard.writeText(c.evidence)}
                              title="Copy evidence"
                              className="text-gray-300 hover:text-gray-500 transition-colors flex-shrink-0"
                            >
                              <Copy size={12} />
                            </button>
                          </div>
                        </div>
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
            <div className="haip-card p-6 text-center border-dashed">
              <Loader2 size={24} className="text-gray-300 mx-auto mb-2 animate-spin" />
              <p className="text-sm text-gray-400">QA analysis in progress…</p>
            </div>
          )}

          {/* Wrap-up panel */}
          <div className="haip-card p-5">
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

            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="w-full py-2.5 bg-[#0F766E] hover:bg-[#0d6660] disabled:opacity-60 text-white font-semibold rounded-xl text-sm transition-colors flex items-center justify-center gap-2"
            >
              {saveMutation.isPending ? (
                <><Loader2 size={14} className="animate-spin" /> Saving…</>
              ) : (
                <><Save size={14} /> Save wrap-up</>
              )}
            </button>
          </div>

          {/* ── Recommended actions zone ─────────────────────────────────────
              Relocated out of Wrap-up so it reads as its own zone rather than
              a sub-item of the human wrap-up form. Same logic as before:
              clickable when a structured recommended_action exists (currently
              only send_whatsapp_draft), otherwise falls back to the free-text
              next_action. */}
          {(call.recommended_action?.type === "send_whatsapp_draft" && call.recommended_action.target_conversation_id) || call.score?.next_action ? (
            <div className="haip-card p-5">
              <h2 className="text-sm font-semibold text-gray-900 mb-3">Recommended actions</h2>
              {call.recommended_action?.type === "send_whatsapp_draft" && call.recommended_action.target_conversation_id ? (
                <div className="p-3 bg-teal-50 border border-teal-100 rounded-xl">
                  {call.score?.next_action && (
                    <p className="text-sm text-teal-800 mb-2">{call.score.next_action}</p>
                  )}
                  <button
                    type="button"
                    onClick={() => approveAndSendMutation.mutate({
                      conversationId: call.recommended_action!.target_conversation_id!,
                      messageId: call.recommended_action!.target,
                    })}
                    disabled={approveAndSendMutation.isPending}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-teal-600 hover:bg-teal-700 disabled:opacity-60 text-white text-xs font-semibold rounded-lg transition-colors"
                  >
                    {approveAndSendMutation.isPending ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <MessageSquare size={12} />
                    )}
                    {call.recommended_action.label}
                  </button>
                </div>
              ) : call.score?.next_action ? (
                <div className="p-3 bg-teal-50 border border-teal-100 rounded-xl">
                  <p className="text-sm text-teal-800">{call.score.next_action}</p>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* ── Insights zone ─────────────────────────────────────────────────
              Groups Layer 2 intent/outcome data with the missed-revenue
              signal under one visual heading — both are AI-derived read-only
              insights, previously split between a standalone Layer2Panel and
              a box buried inside the Wrap-up form. No data/logic changes,
              presentation only. */}
          {(call.layer2 || (call.score?.missed_revenue && call.score.missed_revenue > 0)) && (
            <div className="space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 px-1">Insights</h2>
              {call.score?.missed_revenue && call.score.missed_revenue > 0 && (
                <div className="p-3 bg-red-50 border border-red-100 rounded-xl">
                  <p className="text-xs font-semibold text-red-600 mb-0.5">Potential missed revenue</p>
                  <p className="text-base font-bold text-red-700">
                    ₹{call.score.missed_revenue.toLocaleString("en-IN")}
                  </p>
                </div>
              )}
              {call.layer2 && <Layer2Panel layer2={call.layer2} />}
            </div>
          )}

          {/* C8: Bookmarked moments panel */}
          {bookmarks.size > 0 && call.transcript?.turns && (
            <div className="haip-card p-5">
              <div className="flex items-center gap-2 mb-3">
                <Star size={14} className="text-amber-400 fill-amber-400" />
                <h3 className="text-sm font-semibold text-gray-900">
                  Bookmarked moments
                  <span className="ml-1.5 text-xs font-normal text-gray-400">({bookmarks.size})</span>
                </h3>
              </div>
              <div className="space-y-2">
                {Array.from(bookmarks)
                  .sort((a, b) => a - b)
                  .map(idx => {
                    const turn = call.transcript!.turns[idx];
                    if (!turn) return null;
                    const mins = Math.floor(turn.t0 / 60);
                    const secs = Math.floor(turn.t0 % 60);
                    const timeStr = `${mins}:${secs.toString().padStart(2, "0")}`;
                    return (
                      <button
                        key={idx}
                        onClick={() => {
                          const audio = document.querySelector("audio") as HTMLAudioElement | null;
                          if (!audio) return;
                          audio.currentTime = turn.t0;
                          audio.play().catch(() => {});
                        }}
                        className="w-full text-left px-3 py-2 rounded-xl bg-amber-50 border border-amber-100 hover:bg-amber-100 transition-colors group"
                      >
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-[10px] font-mono font-semibold text-amber-600">{timeStr}</span>
                          <span className="text-[10px] text-amber-500 capitalize">{turn.speaker}</span>
                        </div>
                        <p className="text-xs text-gray-700 line-clamp-2">{turn.text}</p>
                      </button>
                    );
                  })}
              </div>
              <button
                onClick={() => setBookmarks(new Set())}
                className="mt-3 text-[11px] text-gray-400 hover:text-red-500 transition-colors"
              >
                Clear all bookmarks
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Layer 2: Intent & Outcome Panel ──────────────────────────────────────────

const OCCASION_LABELS: Record<string, { label: string; color: string; emoji: string }> = {
  honeymoon:   { label: "Honeymoon",   color: "bg-pink-500/10 text-pink-400 border-pink-500/20",   emoji: "💑" },
  anniversary: { label: "Anniversary", color: "bg-rose-500/10 text-rose-400 border-rose-500/20",   emoji: "🥂" },
  birthday:    { label: "Birthday",    color: "bg-amber-500/10 text-amber-400 border-amber-500/20", emoji: "🎂" },
  corporate:   { label: "Corporate",   color: "bg-blue-500/10 text-blue-400 border-blue-500/20",    emoji: "💼" },
  family:      { label: "Family",      color: "bg-teal-500/10 text-teal-400 border-teal-500/20",    emoji: "👨‍👩‍👧" },
  solo:        { label: "Solo",        color: "bg-purple-500/10 text-purple-400 border-purple-500/20", emoji: "🧘" },
  wedding:     { label: "Wedding",     color: "bg-pink-500/10 text-pink-400 border-pink-500/20",    emoji: "💒" },
  other:       { label: "Other",       color: "bg-muted text-muted-foreground border-border",        emoji: "✈️" },
};

const DECISION_STAGE_LABELS: Record<string, { label: string; color: string }> = {
  first_inquiry:  { label: "First inquiry",   color: "text-blue-400" },
  comparing:      { label: "Comparing options", color: "text-amber-400" },
  ready_to_book:  { label: "Ready to book",   color: "text-teal-400" },
};

const LOST_REASON_LABELS: Record<string, string> = {
  price:              "Price too high",
  dates_unavailable:  "Dates not available",
  still_comparing:    "Still comparing",
  no_response:        "No response",
  wrong_property:     "Wrong property type",
  other:              "Other reason",
};

function ConversionRing({ probability }: { probability: number }) {
  const r = 22;
  const circ = 2 * Math.PI * r;
  const fill = (probability / 100) * circ;
  const color = probability >= 70 ? "#14b8a6" : probability >= 40 ? "#f59e0b" : "#ef4444";
  return (
    <div className="relative w-14 h-14 flex items-center justify-center flex-shrink-0">
      <svg width="56" height="56" viewBox="0 0 56 56" className="-rotate-90">
        <circle cx="28" cy="28" r={r} fill="none" stroke="currentColor" strokeWidth="4"
          className="text-border" />
        <circle cx="28" cy="28" r={r} fill="none" stroke={color} strokeWidth="4"
          strokeDasharray={`${fill} ${circ}`} strokeLinecap="round" />
      </svg>
      <span className="absolute text-xs font-bold" style={{ color }}>{probability}%</span>
    </div>
  );
}

function Layer2Panel({ layer2 }: { layer2: Layer2 }) {
  const hasAnyData = layer2.occasion || layer2.budget_signal || layer2.decision_stage ||
    layer2.competitor_mentioned || layer2.conversion_probability != null || layer2.lost_reason;

  if (!hasAnyData) return null;

  const occasion = layer2.occasion ? OCCASION_LABELS[layer2.occasion] : null;
  const decisionStage = layer2.decision_stage ? DECISION_STAGE_LABELS[layer2.decision_stage] : null;

  return (
    <div className="bg-card border border-border rounded-2xl shadow-sm p-5">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <div className="w-7 h-7 rounded-lg bg-teal-500/10 border border-teal-500/20 flex items-center justify-center flex-shrink-0">
          <Layers size={14} className="text-teal-400" />
        </div>
        <h2 className="text-sm font-semibold text-foreground">Intent & Outcome</h2>
        <span className="ml-auto text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 bg-muted px-2 py-0.5 rounded-full">
          Layer 2 AI
        </span>
      </div>

      <div className="space-y-3">
        {/* Conversion probability + occasion on same row */}
        <div className="flex items-center gap-3">
          {layer2.conversion_probability != null && (
            <div className="flex items-center gap-3 flex-1">
              <ConversionRing probability={layer2.conversion_probability} />
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-0.5">
                  Conversion probability
                </p>
                <p className={cn(
                  "text-sm font-bold",
                  layer2.conversion_probability >= 70 ? "text-teal-400"
                  : layer2.conversion_probability >= 40 ? "text-amber-400"
                  : "text-red-400"
                )}>
                  {layer2.conversion_probability >= 70 ? "High chance" :
                   layer2.conversion_probability >= 40 ? "Medium chance" : "Low chance"}
                </p>
              </div>
            </div>
          )}
          {occasion && (
            <div className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold",
              occasion.color
            )}>
              <span>{occasion.emoji}</span>
              {occasion.label}
            </div>
          )}
        </div>

        {/* Decision stage */}
        {decisionStage && (
          <div className="flex items-center gap-2.5 py-2 border-t border-border">
            <Target size={13} className="text-muted-foreground flex-shrink-0" />
            <div className="flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Decision stage
              </p>
              <p className={cn("text-sm font-semibold mt-0.5", decisionStage.color)}>
                {decisionStage.label}
              </p>
            </div>
          </div>
        )}

        {/* Budget signal */}
        {layer2.budget_signal && (
          <div className="flex items-start gap-2.5 py-2 border-t border-border">
            <TrendingUp size={13} className="text-muted-foreground flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Budget signal
              </p>
              <p className="text-sm text-foreground mt-0.5 italic">
                &ldquo;{layer2.budget_signal}&rdquo;
              </p>
            </div>
          </div>
        )}

        {/* Competitor mentioned */}
        {layer2.competitor_mentioned && (
          <div className="flex items-start gap-2.5 py-2 border-t border-border">
            <AlertTriangle size={13} className="text-amber-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Competitor mentioned
              </p>
              <p className="text-sm font-semibold text-amber-400 mt-0.5">
                {layer2.competitor_mentioned}
              </p>
            </div>
          </div>
        )}

        {/* Lost reason */}
        {layer2.lost_reason && (
          <div className="flex items-start gap-2.5 py-2 border-t border-border">
            <AlertCircle size={13} className="text-red-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Lost reason
              </p>
              <p className="text-sm font-semibold text-red-400 mt-0.5">
                {LOST_REASON_LABELS[layer2.lost_reason] ?? layer2.lost_reason}
              </p>
            </div>
          </div>
        )}

        {/* Language */}
        {layer2.detected_language && (
          <div className="flex items-center gap-2.5 py-2 border-t border-border">
            <Globe size={13} className="text-muted-foreground flex-shrink-0" />
            <div className="flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Language
              </p>
              <p className="text-sm text-foreground mt-0.5">
                {layer2.detected_language.toUpperCase()}
                {layer2.is_code_mixed && (
                  <span className="ml-2 text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded-full">
                    code-mixed
                  </span>
                )}
              </p>
            </div>
          </div>
        )}
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
