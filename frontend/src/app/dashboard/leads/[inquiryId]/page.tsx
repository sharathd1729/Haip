"use client";
import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Sparkles, Phone, MessageSquare, Instagram, Building2, Clock, RefreshCw, Plus, Globe, Shield, Star, Timer, Users, MapPin, IndianRupee, Heart, FileText } from "@/lib/icons";
import api from "@/lib/api";
import { timeAgo, cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { SignalDrawer } from "@/components/leads/SignalDrawer";
import { ResponseTimeBadge, formatDuration } from "@/components/leads/LeadCard";
import { useToast } from "@/components/ui/toast";
import { useSession } from "next-auth/react";
import { AIRecommendationCard, type RecommendedAction } from "@/components/ai/AIRecommendationCard";
import { SalesActionCard } from "@/components/sales/SalesActionCard";

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
  option_rank?: number;
  payment_link_status?: "created" | "paid" | "expired" | "cancelled" | null;
  booking_id?: string | null;
}

const QUOTE_LINK_LABEL = { created: "Link sent", paid: "Paid", expired: "Link expired", cancelled: "Link cancelled" } as const;

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
  unanswered_questions?: string[];
  requirements?: string[];
  inferences?: string[];
  follow_up?: string | null;
  booking_status?: { state: string; payment?: string | null; stays?: number } | null;
}

const BOOKING_STATE_LABEL: Record<string, string> = {
  none: "No booking yet",
  confirmed: "Booked",
  checked_in: "Checked in",
  checked_out: "Stay completed",
  cancelled: "Booking cancelled",
};
const BOOKING_PAYMENT_LABEL: Record<string, string> = { unpaid: "no payment yet", partial: "part-paid", paid: "fully paid" };

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
  if (c === "whatsapp") return <MessageSquare size={12} className="text-[var(--haip-status-success-fg)]" />;
  if (c === "call" || c === "voice") return <Phone size={12} className="text-[var(--haip-status-info-fg)]" />;
  if (c === "system") return <Shield size={12} className="text-[var(--haip-fg-subtle)]" />;
  if (c === "web") return <Globe size={12} className="text-[var(--haip-fg-subtle)]" />;
  return <MessageSquare size={12} className="text-[var(--haip-fg-subtle)]" />;
}

// ─── Completeness bar ─────────────────────────────────────────────────────────

function CompletenessBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? "#10B981" : pct >= 50 ? "#F59E0B" : "#6B7280";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-[var(--haip-fg-subtle)]">Profile completeness</span>
        <span className="font-medium" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--haip-surface)]">
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
  whatsapp: { in: "bg-[var(--haip-status-success-bg)] border-[var(--haip-status-success-border)] text-[var(--haip-fg)]", out: "bg-primary text-primary-foreground" },
  instagram: { in: "bg-[var(--haip-surface)] border-[var(--haip-border)] text-[var(--haip-fg)]", out: "bg-primary text-primary-foreground" },
};

interface CallTranscriptTurn {
  speaker: string;
  text: string;
  t0: number;
  t1: number;
}

function CallBreakdownPill({ label }: { label: string }) {
  return (
    <span className="text-[9.5px] bg-[var(--haip-card)] border border-[var(--haip-status-info-border)] text-[var(--haip-status-info-fg)] px-1.5 py-0.5 rounded-full capitalize">
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
    <div className="mx-auto w-full max-w-[420px] rounded-xl border border-[var(--haip-status-info-border)] bg-[var(--haip-status-info-bg)] p-3 space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-[var(--haip-status-info-fg)]">
          <Phone size={11} />
          {entry.direction === "inbound" ? "Inbound call" : "Outbound call"}
        </span>
        <span className="text-[9px] text-[var(--haip-fg-subtle)]">{timeAgo(entry.occurred_at)}</span>
      </div>
      <div className="flex items-center gap-3 text-[10px] text-[var(--haip-status-info-fg)]">
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
        <p className="text-[11px] text-[var(--haip-fg-2)] leading-relaxed line-clamp-3">{entry.call_summary}</p>
      )}
      {entry.call_next_action && (
        <p className="text-[11px] font-medium text-[var(--haip-status-info-fg)] border-t border-[var(--haip-status-info-border)] pt-1.5">
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
            className="text-[10px] font-medium text-[var(--haip-status-info-fg)] hover:underline"
          >
            {showTranscript ? "Hide transcript" : "View full transcript"}
          </button>
          {showTranscript && (
            <div className="mt-1.5 max-h-56 overflow-y-auto space-y-1.5 bg-[var(--haip-card)] rounded-lg border border-[var(--haip-status-info-border)] p-2">
              {loadingTranscript ? (
                <p className="text-[10px] text-[var(--haip-fg-subtle)]">Loading…</p>
              ) : (detail?.transcript?.turns ?? []).length === 0 ? (
                <p className="text-[10px] text-[var(--haip-fg-subtle)]">No transcript available.</p>
              ) : (
                (detail.transcript.turns as CallTranscriptTurn[]).map((t, i) => (
                  <p key={i} className="text-[10.5px] leading-relaxed">
                    <span className={cn("font-semibold capitalize", t.speaker === "agent" ? "text-[var(--haip-status-info-fg)]" : "text-[var(--haip-fg-2)]")}>
                      {t.speaker}:
                    </span>{" "}
                    <span className="text-[var(--haip-fg-2)]">{t.text}</span>
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
                ? "bg-primary border-primary text-primary-foreground font-medium"
                : "bg-[var(--haip-card)] border-[var(--haip-border)] text-[var(--haip-fg-subtle)] hover:border-primary/40"
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <p className="text-[11px] text-[var(--haip-fg-subtle)] text-center py-8">No messages on this channel yet</p>
      ) : (
        <div className="space-y-2.5">
          {visible.map(entry => {
            const c = entry.channel.toLowerCase();
            if (c === "call" || c === "voice") return <CallCard key={entry.id} entry={entry} />;
            if (c === "system") {
              return (
                <p key={entry.id} className="text-center text-[10px] text-[var(--haip-fg-subtle)] py-1">
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
                  <div className={cn("flex items-center gap-1.5 mt-1", inbound ? "text-[var(--haip-fg-subtle)]" : "text-primary-foreground/80")}>
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
  positive: "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)] border-[var(--haip-status-success-border)]",
  neutral: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] border-[var(--haip-status-neutral-border)]",
  hesitant: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]",
  negative: "bg-rose-50 text-rose-700 border-rose-100",
};

const URGENCY_TONE: Record<string, string> = {
  high: "bg-rose-50 text-rose-700 border-rose-100",
  medium: "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)] border-[var(--haip-status-warning-border)]",
  low: "bg-[var(--haip-status-neutral-bg)] text-[var(--haip-status-neutral-fg)] border-[var(--haip-status-neutral-border)]",
};

function AnalysisRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 border-b border-[var(--haip-border)] last:border-0">
      <span className="text-[10px] uppercase tracking-wide text-[var(--haip-fg-subtle)] pt-0.5 flex-shrink-0">{label}</span>
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
      <div className="bg-primary/10 rounded-xl border border-primary/20 p-3.5">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Sparkles size={13} className="text-primary" />
          <span className="text-[11px] font-semibold text-primary">AI Summary</span>
        </div>
        {summary ? (
          <p className="text-[12px] text-primary leading-relaxed">{summary}</p>
        ) : (
          <p className="text-[11px] text-primary/70 italic">Generating summary… refresh in a moment.</p>
        )}
      </div>

      {analysis ? (
        <div className="bg-[var(--haip-card)] rounded-xl border border-[var(--haip-border)] px-3.5 py-1">
          <AnalysisRow label="Intent">
            <span className="text-[12px] text-[var(--haip-fg)]">{analysis.intent || "—"}</span>
          </AnalysisRow>
          <AnalysisRow label="Sentiment">
            <span className={cn("text-[11px] px-2 py-0.5 rounded-full border capitalize", SENTIMENT_TONE[analysis.sentiment ?? ""] ?? SENTIMENT_TONE.neutral)}>
              {analysis.sentiment || "unknown"}
            </span>
          </AnalysisRow>
          <AnalysisRow label="Objection">
            <span className="text-[12px] text-[var(--haip-fg)]">{analysis.objection || "None detected"}</span>
          </AnalysisRow>
          <AnalysisRow label="Reply urgency">
            <span className={cn("text-[11px] px-2 py-0.5 rounded-full border capitalize", URGENCY_TONE[analysis.reply_urgency ?? ""] ?? URGENCY_TONE.low)}>
              {analysis.reply_urgency || "unknown"}
            </span>
          </AnalysisRow>
          <AnalysisRow label="Next action">
            <span className="text-[12px] font-medium text-primary">{analysis.next_action || "—"}</span>
          </AnalysisRow>
          {!!analysis.unanswered_questions?.length && (
            <AnalysisRow label="Not answered yet">
              <span className="text-[12px] text-[var(--haip-fg)]">{analysis.unanswered_questions.join(" · ")}</span>
            </AnalysisRow>
          )}
          {!!analysis.requirements?.length && (
            <AnalysisRow label="Asked for">
              <span className="text-[12px] text-[var(--haip-fg)]">{analysis.requirements.join(" · ")}</span>
            </AnalysisRow>
          )}
          {analysis.follow_up && (
            <AnalysisRow label="Follow up">
              <span className="text-[12px] text-[var(--haip-fg)]">{analysis.follow_up}</span>
            </AnalysisRow>
          )}
          {analysis.booking_status && (
            <AnalysisRow label="Booking">
              <span className="text-[12px] text-[var(--haip-fg)]">
                {BOOKING_STATE_LABEL[analysis.booking_status.state] ?? analysis.booking_status.state}
                {analysis.booking_status.payment ? ` — ${BOOKING_PAYMENT_LABEL[analysis.booking_status.payment] ?? analysis.booking_status.payment}` : ""}
              </span>
            </AnalysisRow>
          )}
          {!!analysis.inferences?.length && (
            <AnalysisRow label="Inferred, not stated">
              <span className="text-[12px] italic text-[var(--haip-fg-subtle)]">{analysis.inferences.join(" · ")}</span>
            </AnalysisRow>
          )}
        </div>
      ) : (
        <div className="bg-[var(--haip-card)] rounded-xl border border-dashed border-[var(--haip-border)] p-5 text-center space-y-2">
          <p className="text-[11px] text-[var(--haip-fg-subtle)]">
            Structured analysis (intent, sentiment, objections, urgency) appears
            after the summary next regenerates.
          </p>
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 text-[11px] font-medium text-primary border border-primary/30 bg-primary/10 hover:bg-primary/15 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
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
    refetchOnWindowFocus: true,       // an owner, stage or source changed on another device shows when this one is picked up
    refetchOnReconnect: true,
    staleTime: 10_000,
  });

  // M5+ WS3: same approve-and-queue endpoint LeadCard's one-click send uses.
  const approveAndSendMutation = useMutation({
    mutationFn: ({ conversationId, messageId }: { conversationId: string; messageId: string }) =>
      api.post(`/conversations/${conversationId}/messages/${messageId}/approve`),
    onSuccess: () => {
      toast({ title: "Draft sent", description: "The WhatsApp reply is on its way.", variant: "success" });
      qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast({ title: "Send failed", description: typeof msg === "string" ? msg : "Please try again.", variant: "error" });
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
      <div className="p-8 text-center text-[var(--haip-fg-subtle)]">
        <p>Lead not found.</p>
        <button onClick={() => router.back()} className="mt-3 text-primary text-sm">← Back</button>
      </div>
    );
  }

  const timelineItems: TimelineEntry[] = data.timeline ?? [];

  // Trip Details card: guests/dates/budget/occasion are already on the
  // LeadDetailSchema response (just weren't rendered on Overview before).
  // special_requests isn't its own field on the schema -- it's seeded as a
  // Lead Field Registry entry (migration 044) and arrives inside
  // custom_field_values, so it's pulled out here rather than duplicated in
  // the generic Details grid below.
  const customFields: FieldValue[] = data.custom_field_values ?? [];
  const specialRequests = customFields.find(f => f.field_key === "special_requests");
  const guestCountLabel = [
    data.adults ? `${data.adults} adult${data.adults > 1 ? "s" : ""}` : null,
    data.children ? `${data.children} child${data.children > 1 ? "ren" : ""}` : null,
  ].filter(Boolean).join(", ") || null;
  const tripDatesLabel = data.check_in
    ? `${data.check_in}${data.check_out ? ` → ${data.check_out}` : ""}`
    : null;
  const tripBudgetLabel = data.budget_range_label
    ?? (data.budget_estimate ? `₹${Number(data.budget_estimate).toLocaleString("en-IN")}` : null);
  // No dedicated route/location field exists in the schema -- property
  // interest is the closest real signal (which property/route the guest
  // is asking about), not an invented value.
  const tripRouteLabel = (data.property_interest ?? [])[0] ?? null;
  const hasTripDetails = guestCountLabel || tripDatesLabel || tripRouteLabel || tripBudgetLabel || data.occasion || specialRequests?.value;

  return (
    <div className="haip-leads-v2 flex flex-col h-full overflow-hidden">
      {/* ── Back header ── */}
      <div className="flex-shrink-0 px-4 pt-3" style={{ borderBottom: "1px solid var(--haip-border)", background: "var(--haip-card)" }}>
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="w-7 h-7 flex items-center justify-center rounded-lg transition-colors"
            style={{ color: "var(--haip-fg-subtle)" }}
          >
            <ArrowLeft size={15} />
          </button>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="font-bold text-[14px] truncate" style={{ color: "var(--haip-fg)" }}>{data.display_name}</h2>
              <ResponseTimeBadge seconds={data.response_time_seconds} status={data.response_time_status} />
            </div>
            <p className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>{data.inquiry_stage} · {data.source?.replace(/_/g, " ")}</p>
          </div>
          <div className="flex items-center gap-1.5">
            {SIGNAL_ROLES.has(role) && (
              <button
                onClick={() => setShowSignalDrawer(true)}
                className="flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-full transition-colors"
                style={{ color: "var(--lx-iris)", background: "var(--lx-iris-soft)", border: "1.5px solid color-mix(in srgb, var(--lx-iris) 35%, transparent)" }}
              >
                <Plus size={11} />
                Add Signal
              </button>
            )}
            <button
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
              className="lx-icon-btn w-7 h-7 flex items-center justify-center border transition-colors"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-subtle)" }}
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
              className={cn("lx-tab text-[12px] pb-2 border-b-2 border-transparent transition-colors -mb-px", tab === t.key && "active font-semibold")}
              style={tab !== t.key ? { color: "var(--haip-fg-subtle)" } : undefined}
            >
              {t.label}
              {t.key === "chat" && timelineItems.length > 0 && (
                <span className="ml-1 text-[9px]" style={{ color: "var(--haip-fg-subtle)" }}>({timelineItems.length})</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Scrollable content ── */}
      <div className="flex-1 overflow-y-auto haip-scrollbar">
        <div className="p-4 space-y-4 max-w-2xl mx-auto">
          <SalesActionCard inquiryId={inquiryId} />

          {tab === "overview" && (
            <>
              {/* Profile card */}
              <div className="lx-dcard p-4 space-y-3">
                <CompletenessBar pct={data.profile_completeness_pct} />

                {/* Identity signals */}
                <div className="flex flex-wrap gap-1.5">
                  {(data.identity_signals ?? []).map((sig: string) => (
                    <span key={sig} className="lx-sig-pill text-[10px] px-2 py-0.5">
                      {sig.replace(/_/g, " ")}
                    </span>
                  ))}
                  {(data.identity_signals ?? []).length === 0 && (
                    <span className="text-[10px] italic" style={{ color: "var(--haip-fg-subtle)" }}>No identity signals yet</span>
                  )}
                </div>
              </div>

              {/* Trip details — guests/dates/property-route/budget/occasion are
                  real LeadDetailSchema fields; special requests comes off the
                  Lead Field Registry (migration 044). No dedicated route/
                  location field exists in the schema, so property_interest[0]
                  stands in for it rather than an invented value. */}
              {hasTripDetails && (
                <div className="lx-dcard p-4">
                  <h3 className="text-[11px] font-bold uppercase tracking-wide mb-3 flex items-center gap-1.5" style={{ color: "var(--haip-fg-subtle)" }}>
                    <FileText size={12} />
                    Trip Details
                  </h3>
                  <div className="lx-trip-grid">
                    {guestCountLabel && (
                      <div className="lx-trip-item">
                        <div className="lx-trip-icon"><Users size={13} /></div>
                        <div className="min-w-0">
                          <p className="text-[9px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>Guests</p>
                          <p className="text-[12px] font-semibold truncate" style={{ color: "var(--haip-fg)" }}>{guestCountLabel}</p>
                        </div>
                      </div>
                    )}
                    {tripDatesLabel && (
                      <div className="lx-trip-item">
                        <div className="lx-trip-icon"><Clock size={13} /></div>
                        <div className="min-w-0">
                          <p className="text-[9px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>Dates</p>
                          <p className="text-[12px] font-semibold tabular-nums truncate" style={{ color: "var(--haip-fg)" }}>{tripDatesLabel}</p>
                        </div>
                      </div>
                    )}
                    {tripRouteLabel && (
                      <div className="lx-trip-item">
                        <div className="lx-trip-icon"><MapPin size={13} /></div>
                        <div className="min-w-0">
                          <p className="text-[9px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>Property / Route</p>
                          <p className="text-[12px] font-semibold truncate" style={{ color: "var(--haip-fg)" }}>{tripRouteLabel}</p>
                        </div>
                      </div>
                    )}
                    {tripBudgetLabel && (
                      <div className="lx-trip-item">
                        <div className="lx-trip-icon"><IndianRupee size={13} /></div>
                        <div className="min-w-0">
                          <p className="text-[9px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>Budget</p>
                          <p className="text-[12px] font-semibold tabular-nums truncate" style={{ color: "var(--haip-fg)" }}>{tripBudgetLabel}</p>
                        </div>
                      </div>
                    )}
                    {data.occasion && (
                      <div className="lx-trip-item">
                        <div className="lx-trip-icon"><Heart size={13} /></div>
                        <div className="min-w-0">
                          <p className="text-[9px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>Occasion</p>
                          <p className="text-[12px] font-semibold capitalize truncate" style={{ color: "var(--haip-fg)" }}>{data.occasion}</p>
                        </div>
                      </div>
                    )}
                    {specialRequests?.value != null && specialRequests.value !== "" && (
                      <div className="lx-trip-item full">
                        <div className="lx-trip-icon"><MessageSquare size={13} /></div>
                        <div className="min-w-0">
                          <p className="text-[9px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>Special Requests</p>
                          <p className="text-[12px] font-medium" style={{ color: "var(--haip-fg)" }}>{formatFieldValue(specialRequests)}</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Lead field registry — remaining tenant-configurable fields not
                  already surfaced in Trip Details above. */}
              {(data.custom_field_values ?? []).filter((f: FieldValue) =>
                !["adults", "children", "check_in", "check_out", "budget", "occasion", "special_requests"].includes(f.field_key)
                && f.value !== null && f.value !== undefined && f.value !== ""
              ).length > 0 && (
                <div className="lx-dcard p-3.5">
                  <h3 className="text-[11px] font-semibold mb-2" style={{ color: "var(--haip-fg-2)" }}>Details</h3>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                    {(data.custom_field_values as FieldValue[])
                      .filter(f =>
                        !["adults", "children", "check_in", "check_out", "budget", "occasion", "special_requests"].includes(f.field_key)
                        && f.value !== null && f.value !== undefined && f.value !== "")
                      .map(f => (
                        <div key={f.field_key} className="min-w-0">
                          <p className="text-[9px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>{f.label}</p>
                          <p className="text-[11px] truncate" style={{ color: "var(--haip-fg-2)" }}>{formatFieldValue(f)}</p>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* AI summary (condensed — full analysis lives in its own tab) */}
              <div className="lx-ai-card p-3.5">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="lx-ai-label flex items-center gap-1.5">
                    <Sparkles size={13} />
                    <span className="text-[11px] font-semibold">AI Summary</span>
                  </div>
                  <button onClick={() => setTab("analysis")} className="lx-ai-label text-[10px] hover:underline">
                    Full analysis →
                  </button>
                </div>
                {data.ai_summary ? (
                  <p className="text-[12px] leading-relaxed" style={{ color: "var(--haip-fg-2)" }}>{data.ai_summary}</p>
                ) : (
                  <p className="lx-ai-label text-[11px] italic">Generating summary… refresh in a moment.</p>
                )}
                {data.ai_next_action && (
                  <p className="lx-ai-next text-[11px] font-medium mt-1.5 pt-1.5">
                    → {data.ai_next_action}
                  </p>
                )}
                {data.pending_draft && (
                  <div className="mt-2 pt-2 flex items-center justify-between gap-2" style={{ borderTop: "1px solid color-mix(in srgb, var(--lx-iris) 25%, transparent)" }}>
                    <p className="lx-ai-label text-[10px] truncate flex-1" title={data.pending_draft.preview}>
                      {data.pending_draft.preview}
                    </p>
                    <button
                      type="button"
                      onClick={() => approveAndSendMutation.mutate({
                        conversationId: data.pending_draft.conversation_id,
                        messageId: data.pending_draft.message_id,
                      })}
                      disabled={approveAndSendMutation.isPending}
                      className="lx-ai-send-btn inline-flex items-center gap-1 px-2.5 py-1 disabled:opacity-60 text-[10px] font-semibold flex-shrink-0 transition-colors"
                    >
                      <MessageSquare size={10} />
                      {approveAndSendMutation.isPending ? "Sending…" : "Send draft"}
                    </button>
                  </div>
                )}
              </div>

              {/* Suggested next step -- "autopilot" pass (Ratha, Sep 2026):
                  same shared AIRecommendationCard the call detail page uses,
                  extended to a lead's own stage/Lost suggestion
                  (lead_recommendation_service.py). Nothing here moves the
                  pipeline until the agent clicks Apply. */}
              {(data.recommended_actions ?? []).length > 0 && (
                <AIRecommendationCard
                  title="Suggested next step"
                  summary={(data.recommended_actions[0] as RecommendedAction & { reason?: string }).reason
                    ?? "AI found something worth acting on for this lead."}
                  entityRefs={{ inquiry_id: inquiryId }}
                  actions={data.recommended_actions}
                  source="lead_detail"
                  invalidateKeys={[["lead", inquiryId]]}
                />
              )}

              {/* Property interest */}
              {(data.property_interest ?? []).length > 0 && (
                <div className="lx-dcard p-3.5">
                  <h3 className="text-[11px] font-semibold mb-2 flex items-center gap-1.5" style={{ color: "var(--haip-fg-2)" }}>
                    <Building2 size={12} style={{ color: "var(--haip-fg-subtle)" }} />
                    Property Interest
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {data.property_interest.map((p: string) => (
                      <span key={p} className="text-[11px] px-2.5 py-1 rounded-lg" style={{ background: "var(--muted)", color: "var(--haip-fg-2)" }}>
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Quote history */}
              {(data.quote_history ?? []).length > 0 && (
                <div className="lx-dcard p-3.5">
                  <h3 className="text-[11px] font-semibold mb-2" style={{ color: "var(--haip-fg-2)" }}>Quote History</h3>
                  <div className="space-y-1.5">
                    {data.quote_history.map((q: QuoteHistory) => (
                      <div
                        key={q.id}
                        className="flex items-center justify-between text-[11px] px-2.5 py-1.5 rounded-lg"
                        style={q.is_active ? { background: "color-mix(in srgb, var(--haip-green) 12%, transparent)" } : { background: "var(--muted)" }}
                      >
                        <span className="font-medium tabular-nums" style={{ color: q.is_active ? "var(--haip-green)" : "var(--haip-fg-2)" }}>
                          {q.currency} {Number(q.amount).toLocaleString("en-IN")}
                          {(q.option_rank ?? 1) === 2 && <span className="ml-1 font-normal text-[var(--haip-fg-subtle)]">option 2</span>}
                        </span>
                        {q.payment_link_status && (
                          q.booking_id
                            ? <Link href={`/dashboard/bookings/${q.booking_id}`} className="font-semibold text-primary hover:underline">Paid · booking</Link>
                            : <span className={q.payment_link_status === "paid" ? "font-semibold text-[var(--haip-status-success-fg)]" : "text-[var(--haip-fg-subtle)]"}>
                                {QUOTE_LINK_LABEL[q.payment_link_status]}
                              </span>
                        )}
                        <span style={{ color: "var(--haip-fg-subtle)" }}>
                          {q.age_days != null ? `${q.age_days}d ago` : "—"}
                          {q.is_active && <span className="ml-1.5 font-medium" style={{ color: "var(--haip-green)" }}>Active</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent activity preview → chat tab */}
              <div className="lx-dcard p-3.5">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-[11px] font-semibold flex items-center gap-1.5" style={{ color: "var(--haip-fg-2)" }}>
                    <Clock size={12} style={{ color: "var(--haip-fg-subtle)" }} />
                    Recent activity
                  </h3>
                  <button onClick={() => setTab("chat")} className="lx-ai-label text-[10px] hover:underline">
                    Open chat history →
                  </button>
                </div>
                {timelineItems.length === 0 ? (
                  <p className="text-[11px] text-center py-3" style={{ color: "var(--haip-fg-subtle)" }}>No messages yet</p>
                ) : (
                  <div className="space-y-2">
                    {timelineItems.slice(0, 3).map(entry => (
                      <div key={entry.id} className="flex items-start gap-2.5">
                        <div className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5" style={{ background: "var(--muted)" }}>
                          <ChannelIcon channel={entry.channel} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-[11px] leading-relaxed line-clamp-2" style={{ color: "var(--haip-fg-2)" }}>
                            {entry.content_preview || entry.call_summary || "—"}
                          </p>
                          <span className="text-[9px]" style={{ color: "var(--haip-fg-subtle)" }}>{timeAgo(entry.occurred_at)}</span>
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
