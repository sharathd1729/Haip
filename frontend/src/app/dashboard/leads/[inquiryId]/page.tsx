"use client";
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Sparkles, Phone, MessageSquare, MessageCircle as Instagram,
  Building2, Clock, RefreshCw, Plus, Globe,
  Shield, Star, Timer,
} from "lucide-react";
import api from "@/lib/api";
import { timeAgo, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { SignalDrawer } from "@/components/leads/SignalDrawer";
import { ResponseTimeBadge, formatDuration } from "@/components/leads/LeadCard";
import { useToast } from "@/components/ui/toast";
import { useSession } from "next-auth/react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface TimelineEntry {
  id: string;
  channel: string;
  direction: string;
  occurred_at: string;
  content_preview: string;
  full_content?: string | null;
  is_ai_generated?: boolean;
  call_summary?: string | null;
  call_duration_seconds?: number | null;
  call_qa_score?: number | null;
  call_has_transcript?: boolean;
  call_next_action?: string | null;
  call_disposition?: string | null;
  call_occasion?: string | null;
  call_budget_signal?: string | null;
  call_decision_stage?: string | null;
  call_competitor_mentioned?: string | null;
  call_conversion_probability?: number | null;
  call_lost_reason?: string | null;
}

interface QuoteHistory {
  id: string;
  amount: number;
  currency: string;
  created_at?: string;
  is_active?: boolean;
  age_days?: number;
}

interface FieldValue {
  field_key: string;
  label: string;
  data_type: string;
  value: unknown;
}

interface AiAnalysis {
  intent?: string | null;
  sentiment?: string | null;
  objection?: string | null;
  reply_urgency?: string | null;
  next_action?: string | null;
}

function formatFieldValue(f: FieldValue): string {
  if (f.value === null || f.value === undefined || f.value === "") return "—";
  if (f.data_type === "currency" && typeof f.value === "number") {
    return `₹${f.value.toLocaleString("en-IN")}`;
  }
  return String(f.value);
}

// ─── Channel icon ─────────────────────────────────────────────────────────────

function ChannelIcon({ channel }: { channel: string }) {
  const c = channel.toLowerCase();
  if (c === "instagram") return <Instagram size={12} className="text-pink-500" />;
  if (c === "whatsapp") return <MessageSquare size={12} className="text-green-500" />;
  if (c === "call" || c === "voice") return <Phone size={12} className="text-blue-500" />;
  if (c === "system") return <Shield size={12} className="text-gray-400" />;
  if (c === "web") return <Globe size={12} className="text-gray-400" />;
  return <MessageSquare size={12} className="text-gray-400" />;
}

// ─── Completeness bar ─────────────────────────────────────────────────────────

function CompletenessBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? "#10B981" : pct >= 50 ? "#F59E0B" : "#6B7280";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-gray-500">Profile completeness</span>
        <span className="font-medium" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-gray-100">
        <div className="h-1.5 rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

// ─── Chat history ─────────────────────────────────────────────────────────────
// WhatsApp/Instagram render as chat bubbles; calls render as a distinct
// summary card (duration + QA + excerpt) instead of being forced into a
// bubble; system events are small centered notes.

const CHANNEL_FILTERS = [
  { key: "all", label: "All" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "instagram", label: "Instagram" },
  { key: "call", label: "Calls" },
] as const;

const BUBBLE_TONES: Record<string, { in: string; out: string }> = {
  whatsapp: { in: "bg-green-50 border-green-100 text-gray-800", out: "bg-teal-600 text-white" },
  instagram: { in: "bg-pink-50 border-pink-100 text-gray-800", out: "bg-teal-600 text-white" },
};

interface CallTranscriptTurn {
  speaker: string;
  text: string;
  t0: number;
  t1: number;
}

function CallBreakdownPill({ label }: { label: string }) {
  return (
    <span className="text-[9.5px] bg-white border border-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full capitalize">
      {label.replace(/_/g, " ")}
    </span>
  );
}

function CallCard({ entry }: { entry: TimelineEntry }) {
  const [showTranscript, setShowTranscript] = useState(false);

  const { data: detail, isLoading: loadingTranscript } = useQuery({
    queryKey: ["call-transcript", entry.id],
    queryFn: () => api.get(`/calls/${entry.id}`).then(r => r.data),
    enabled: showTranscript,
    staleTime: 60_000,
  });

  const breakdownPills = [
    entry.call_occasion,
    entry.call_decision_stage?.replace(/_/g, " "),
    entry.call_competitor_mentioned && `vs. ${entry.call_competitor_mentioned}`,
    entry.call_lost_reason && `lost: ${entry.call_lost_reason}`,
  ].filter(Boolean) as string[];

  return (
    <div className="mx-auto w-full max-w-[420px] rounded-xl border border-blue-100 bg-blue-50/60 p-3 space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-blue-700">
          <Phone size={11} />
          {entry.direction === "inbound" ? "Inbound call" : "Outbound call"}
        </span>
        <span className="text-[9px] text-gray-400">{timeAgo(entry.occurred_at)}</span>
      </div>
      <div className="flex items-center gap-3 text-[10px] text-blue-800">
        {entry.call_duration_seconds != null && (
          <span className="flex items-center gap-1">
            <Timer size={10} /> {formatDuration(entry.call_duration_seconds)}
          </span>
        )}
        {entry.call_qa_score != null && (
          <span className="flex items-center gap-1">
            <Star size={10} /> QA {Math.round(entry.call_qa_score)}/100
          </span>
        )}
        {entry.call_disposition && (
          <span className="capitalize">{entry.call_disposition.replace(/_/g, " ")}</span>
        )}
        {entry.call_conversion_probability != null && (
          <span>{entry.call_conversion_probability}% likely to book</span>
        )}
      </div>
      {entry.call_summary && (
        <p className="text-[11px] text-gray-700 leading-relaxed line-clamp-3">{entry.call_summary}</p>
      )}
      {entry.call_next_action && (
        <p className="text-[11px] font-medium text-blue-700 border-t border-blue-100 pt-1.5">
          → {entry.call_next_action}
        </p>
      )}
      {breakdownPills.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {breakdownPills.map((p, i) => <CallBreakdownPill key={i} label={p} />)}
        </div>
      )}
      {entry.call_has_transcript && (
        <div>
          <button
            onClick={() => setShowTranscript(v => !v)}
            className="text-[10px] font-medium text-blue-600 hover:underline"
          >
            {showTranscript ? "Hide transcript" : "View full transcript"}
          </button>
          {showTranscript && (
            <div className="mt-1.5 max-h-56 overflow-y-auto space-y-1.5 bg-white rounded-lg border border-blue-100 p-2">
              {loadingTranscript ? (
                <p className="text-[10px] text-gray-400">Loading…</p>
              ) : (detail?.transcript?.turns ?? []).length === 0 ? (
                <p className="text-[10px] text-gray-400">No transcript available.</p>
              ) : (
                (detail.transcript.turns as CallTranscriptTurn[]).map((t, i) => (
                  <p key={i} className="text-[10.5px] leading-relaxed">
                    <span className={cn("font-semibold capitalize", t.speaker === "agent" ? "text-blue-700" : "text-gray-700")}>
                      {t.speaker}:
                    </span>{" "}
                    <span className="text-gray-600">{t.text}</span>
                  </p>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChatHistoryTab({ items }: { items: TimelineEntry[] }) {
  const [filter, setFilter] = useState<string>("all");

  // Timeline arrives newest-first; a chat reads oldest-first.
  const chronological = [...items].reverse();
  const visible = chronological.filter(e => {
    if (filter === "all") return true;
    const c = e.channel.toLowerCase();
    return filter === "call" ? c === "call" || c === "voice" : c === filter;
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        {CHANNEL_FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "text-[11px] px-2.5 py-1 rounded-full border transition-colors",
              filter === f.key
                ? "bg-teal-600 border-teal-600 text-white font-medium"
                : "bg-white border-gray-200 text-gray-500 hover:border-teal-300"
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <p className="text-[11px] text-gray-400 text-center py-8">No messages on this channel yet</p>
      ) : (
        <div className="space-y-2.5">
          {visible.map(entry => {
            const c = entry.channel.toLowerCase();
            if (c === "call" || c === "voice") return <CallCard key={entry.id} entry={entry} />;
            if (c === "system") {
              return (
                <p key={entry.id} className="text-center text-[10px] text-gray-400 py-1">
                  {entry.content_preview} · {timeAgo(entry.occurred_at)}
                </p>
              );
            }
            const inbound = entry.direction === "inbound";
            const tones = BUBBLE_TONES[c] ?? BUBBLE_TONES.whatsapp;
            return (
              <div key={entry.id} className={cn("flex", inbound ? "justify-start" : "justify-end")}>
                <div className={cn("max-w-[75%] rounded-2xl px-3 py-2 border", inbound ? cn(tones.in, "rounded-bl-sm") : cn(tones.out, "border-transparent rounded-br-sm"))}>
                  <p className="text-[12px] leading-relaxed whitespace-pre-wrap break-words">
                    {entry.full_content || entry.content_preview || "—"}
                  </p>
                  <div className={cn("flex items-center gap-1.5 mt-1", inbound ? "text-gray-400" : "text-teal-100")}>
                    <ChannelIcon channel={entry.channel} />
                    <span className="text-[9px]">{timeAgo(entry.occurred_at)}</span>
                    {entry.is_ai_generated && <span className="text-[9px] font-medium">AI</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── AI analysis tab ──────────────────────────────────────────────────────────

const SENTIMENT_TONE: Record<string, string> = {
  positive: "bg-green-50 text-green-700 border-green-100",
  neutral: "bg-gray-50 text-gray-600 border-gray-100",
  hesitant: "bg-amber-50 text-amber-700 border-amber-100",
  negative: "bg-rose-50 text-rose-700 border-rose-100",
};

const URGENCY_TONE: Record<string, string> = {
  high: "bg-rose-50 text-rose-700 border-rose-100",
  medium: "bg-amber-50 text-amber-700 border-amber-100",
  low: "bg-gray-50 text-gray-600 border-gray-100",
};

function AnalysisRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 border-b border-gray-50 last:border-0">
      <span className="text-[10px] uppercase tracking-wide text-gray-400 pt-0.5 flex-shrink-0">{label}</span>
      <div className="text-right">{children}</div>
    </div>
  );
}

function AiAnalysisTab({
  analysis, summary, onRefresh, refreshing,
}: {
  analysis: AiAnalysis | null;
  summary: string | null;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  return (
    <div className="space-y-3">
      {/* Prose summary always shown */}
      <div className="bg-teal-50 rounded-xl border border-teal-100 p-3.5">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Sparkles size={13} className="text-teal-600" />
          <span className="text-[11px] font-semibold text-teal-700">AI Summary</span>
        </div>
        {summary ? (
          <p className="text-[12px] text-teal-800 leading-relaxed">{summary}</p>
        ) : (
          <p className="text-[11px] text-teal-500 italic">Generating summary… refresh in a moment.</p>
        )}
      </div>

      {analysis ? (
        <div className="bg-white rounded-xl border border-gray-100 px-3.5 py-1">
          <AnalysisRow label="Intent">
            <span className="text-[12px] text-gray-800">{analysis.intent || "—"}</span>
          </AnalysisRow>
          <AnalysisRow label="Sentiment">
            <span className={cn("text-[11px] px-2 py-0.5 rounded-full border capitalize", SENTIMENT_TONE[analysis.sentiment ?? ""] ?? SENTIMENT_TONE.neutral)}>
              {analysis.sentiment || "unknown"}
            </span>
          </AnalysisRow>
          <AnalysisRow label="Objection">
            <span className="text-[12px] text-gray-800">{analysis.objection || "None detected"}</span>
          </AnalysisRow>
          <AnalysisRow label="Reply urgency">
            <span className={cn("text-[11px] px-2 py-0.5 rounded-full border capitalize", URGENCY_TONE[analysis.reply_urgency ?? ""] ?? URGENCY_TONE.low)}>
              {analysis.reply_urgency || "unknown"}
            </span>
          </AnalysisRow>
          <AnalysisRow label="Next action">
            <span className="text-[12px] font-medium text-teal-700">{analysis.next_action || "—"}</span>
          </AnalysisRow>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-dashed border-gray-200 p-5 text-center space-y-2">
          <p className="text-[11px] text-gray-500">
            Structured analysis (intent, sentiment, objections, urgency) appears
            after the summary next regenerates.
          </p>
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 text-[11px] font-medium text-teal-600 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={11} className={refreshing ? "animate-spin" : ""} />
            Generate now
          </button>
        </div>
      )}
    </div>
  );
}

// ─── SIGNAL type role check ───────────────────────────────────────────────────

const SIGNAL_ROLES = new Set(["owner", "manager", "reservations"]);

// ─── Page ─────────────────────────────────────────────────────────────────────

type TabKey = "overview" | "chat" | "analysis";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "chat", label: "Chat history" },
  { key: "analysis", label: "AI analysis" },
];

export default function LeadDetailPage() {
  const { inquiryId } = useParams<{ inquiryId: string }>();
  const router = useRouter();
  const { data: session } = useSession();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const role = (session?.user as any)?.role ?? "";
  const { toast } = useToast();
  const qc = useQueryClient();

  const [showSignalDrawer, setShowSignalDrawer] = useState(false);
  const [tab, setTab] = useState<TabKey>("overview");

  const { data, isLoading } = useQuery({
    queryKey: ["lead", inquiryId],
    queryFn: async () => {
      const res = await api.get(`/leads/${inquiryId}`);
      return res.data;
    },
  });

  const refreshMutation = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/refresh-summary`),
    onSuccess: () => {
      toast({ title: "Summary queued", description: "AI summary is being regenerated." });
      setTimeout(() => qc.invalidateQueries({ queryKey: ["lead", inquiryId] }), 5000);
    },
  });

  if (isLoading) {
    return (
      <div className="p-5 space-y-3">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-8 text-center text-gray-500">
        <p>Lead not found.</p>
        <button onClick={() => router.back()} className="mt-3 text-teal-600 text-sm">← Back</button>
      </div>
    );
  }

  const timelineItems: TimelineEntry[] = data.timeline ?? [];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Back header ── */}
      <div className="flex-shrink-0 px-4 pt-3 border-b border-gray-100 bg-white">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <ArrowLeft size={15} />
          </button>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="font-bold text-[14px] text-gray-900 truncate">{data.display_name}</h2>
              <ResponseTimeBadge seconds={data.response_time_seconds} status={data.response_time_status} />
            </div>
            <p className="text-[10px] text-gray-400">{data.inquiry_stage} · {data.source?.replace(/_/g, " ")}</p>
          </div>
          <div className="flex items-center gap-1.5">
            {SIGNAL_ROLES.has(role) && (
              <button
                onClick={() => setShowSignalDrawer(true)}
                className="flex items-center gap-1 text-[11px] font-medium text-teal-600 border border-teal-200 bg-teal-50 hover:bg-teal-100 px-2.5 py-1.5 rounded-lg transition-colors"
              >
                <Plus size={11} />
                Add Signal
              </button>
            )}
            <button
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
              className="w-7 h-7 flex items-center justify-center rounded-lg border border-gray-200 text-gray-400 hover:text-teal-600 hover:border-teal-200 transition-colors"
              title="Refresh AI summary"
            >
              <RefreshCw size={12} className={refreshMutation.isPending ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-4 mt-2">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cn(
                "text-[12px] pb-2 border-b-2 transition-colors -mb-px",
                tab === t.key
                  ? "border-teal-600 text-teal-700 font-semibold"
                  : "border-transparent text-gray-400 hover:text-gray-600"
              )}
            >
              {t.label}
              {t.key === "chat" && timelineItems.length > 0 && (
                <span className="ml-1 text-[9px] text-gray-400">({timelineItems.length})</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div className="flex-1 overflow-y-auto haip-scrollbar">
        <div className="p-4 space-y-4 max-w-2xl mx-auto">

          {tab === "overview" && (
            <>
              {/* Profile card */}
              <div className="bg-white rounded-xl border border-gray-100 p-4 space-y-3">
                <CompletenessBar pct={data.profile_completeness_pct} />

                {/* Identity signals */}
                <div className="flex flex-wrap gap-1.5">
                  {(data.identity_signals ?? []).map((sig: string) => (
                    <span key={sig} className="text-[10px] bg-teal-50 text-teal-700 border border-teal-100 px-2 py-0.5 rounded-full">
                      {sig.replace(/_/g, " ")}
                    </span>
                  ))}
                  {(data.identity_signals ?? []).length === 0 && (
                    <span className="text-[10px] text-gray-400 italic">No identity signals yet</span>
                  )}
                </div>

                {/* Trip intent */}
                {(data.occasion || data.check_in || data.budget_estimate) && (
                  <div className="flex flex-wrap gap-2 text-[11px] text-gray-600 border-t border-gray-50 pt-2">
                    {data.occasion && <span className="capitalize">{data.occasion}</span>}
                    {data.group_type && data.group_type !== data.occasion && (
                      <span className="capitalize text-gray-400">{data.group_type?.replace(/_/g, " ")}</span>
                    )}
                    {data.check_in && <span>{data.check_in}{data.check_out ? ` → ${data.check_out}` : ""}</span>}
                    {data.budget_estimate && (
                      <span className="font-medium">₹{Number(data.budget_estimate).toLocaleString("en-IN")}</span>
                    )}
                  </div>
                )}
              </div>

              {/* Lead field registry — tenant-configurable field catalog (Phase 3) */}
              {(data.custom_field_values ?? []).length > 0 && (
                <div className="bg-white rounded-xl border border-gray-100 p-3.5">
                  <h3 className="text-[11px] font-semibold text-gray-700 mb-2">Details</h3>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                    {(data.custom_field_values as FieldValue[])
                      .filter(f => f.value !== null && f.value !== undefined && f.value !== "")
                      .map(f => (
                        <div key={f.field_key} className="min-w-0">
                          <p className="text-[9px] text-gray-400 uppercase tracking-wide">{f.label}</p>
                          <p className="text-[11px] text-gray-700 truncate">{formatFieldValue(f)}</p>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* AI summary (condensed — full analysis lives in its own tab) */}
              <div className="bg-teal-50 rounded-xl border border-teal-100 p-3.5">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <Sparkles size={13} className="text-teal-600" />
                    <span className="text-[11px] font-semibold text-teal-700">AI Summary</span>
                  </div>
                  <button onClick={() => setTab("analysis")} className="text-[10px] text-teal-600 hover:underline">
                    Full analysis →
                  </button>
                </div>
                {data.ai_summary ? (
                  <p className="text-[12px] text-teal-800 leading-relaxed">{data.ai_summary}</p>
                ) : (
                  <p className="text-[11px] text-teal-500 italic">Generating summary… refresh in a moment.</p>
                )}
                {data.ai_next_action && (
                  <p className="text-[11px] text-teal-600 font-medium mt-1.5 border-t border-teal-100 pt-1.5">
                    → {data.ai_next_action}
                  </p>
                )}
              </div>

              {/* Property interest */}
              {(data.property_interest ?? []).length > 0 && (
                <div className="bg-white rounded-xl border border-gray-100 p-3.5">
                  <h3 className="text-[11px] font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
                    <Building2 size={12} className="text-gray-400" />
                    Property Interest
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {data.property_interest.map((p: string) => (
                      <span key={p} className="text-[11px] bg-gray-50 border border-gray-100 text-gray-700 px-2.5 py-1 rounded-lg">
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Quote history */}
              {(data.quote_history ?? []).length > 0 && (
                <div className="bg-white rounded-xl border border-gray-100 p-3.5">
                  <h3 className="text-[11px] font-semibold text-gray-700 mb-2">Quote History</h3>
                  <div className="space-y-1.5">
                    {data.quote_history.map((q: QuoteHistory) => (
                      <div key={q.id} className={cn("flex items-center justify-between text-[11px] px-2.5 py-1.5 rounded-lg", q.is_active ? "bg-teal-50 border border-teal-100" : "bg-gray-50")}>
                        <span className={cn("font-medium", q.is_active ? "text-teal-700" : "text-gray-600")}>
                          {q.currency} {Number(q.amount).toLocaleString("en-IN")}
                        </span>
                        <span className="text-gray-400">
                          {q.age_days != null ? `${q.age_days}d ago` : "—"}
                          {q.is_active && <span className="ml-1.5 text-teal-600 font-medium">Active</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent activity preview → chat tab */}
              <div className="bg-white rounded-xl border border-gray-100 p-3.5">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-[11px] font-semibold text-gray-700 flex items-center gap-1.5">
                    <Clock size={12} className="text-gray-400" />
                    Recent activity
                  </h3>
                  <button onClick={() => setTab("chat")} className="text-[10px] text-teal-600 hover:underline">
                    Open chat history →
                  </button>
                </div>
                {timelineItems.length === 0 ? (
                  <p className="text-[11px] text-gray-400 text-center py-3">No messages yet</p>
                ) : (
                  <div className="space-y-2">
                    {timelineItems.slice(0, 3).map(entry => (
                      <div key={entry.id} className="flex items-start gap-2.5">
                        <div className="flex-shrink-0 w-6 h-6 rounded-full bg-gray-50 border border-gray-100 flex items-center justify-center mt-0.5">
                          <ChannelIcon channel={entry.channel} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-[11px] text-gray-700 leading-relaxed line-clamp-2">
                            {entry.content_preview || entry.call_summary || "—"}
                          </p>
                          <span className="text-[9px] text-gray-400">{timeAgo(entry.occurred_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          {tab === "chat" && <ChatHistoryTab items={timelineItems} />}

          {tab === "analysis" && (
            <AiAnalysisTab
              analysis={data.ai_analysis ?? null}
              summary={data.ai_summary ?? null}
              onRefresh={() => refreshMutation.mutate()}
              refreshing={refreshMutation.isPending}
            />
          )}

        </div>
      </div>

      {/* ── Signal drawer ── */}
      {showSignalDrawer && (
        <SignalDrawer
          inquiryId={inquiryId}
          onClose={() => setShowSignalDrawer(false)}
          onSuccess={() => qc.invalidateQueries({ queryKey: ["lead", inquiryId] })}
        />
      )}
    </div>
  );
}
