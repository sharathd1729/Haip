"use client";
import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Phone, Upload, X, Filter, Calendar, Sparkles,
  Search, ChevronRight, TrendingUp, TrendingDown, Minus, AlertCircle,
  MessageSquare, Loader2, PhoneIncoming, PhoneOutgoing, PhoneMissed,
  Delete, PhoneCall,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyCalls } from "@/components/empty-states/EmptyCalls";
import { Skeleton } from "@/components/ui/skeleton";
// B5: only needed once the user opens the upload dialog -- keep it out of
// this route's initial chunk.
const UploadModal = dynamic(
  () => import("@/components/calls/UploadModal").then(m => m.UploadModal),
  { ssr: false }
);
import { useCallsStore, type CallFilters } from "@/store/calls";
import { useToast } from "@/components/ui/toast";
import { MobileFilterSheet, MobileFilterTrigger } from "@/components/ui/MobileFilterSheet";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CallItem {
  id: string;
  started_at: string;
  duration_seconds: number;
  direction: "inbound" | "outbound";
  is_missed?: boolean;
  guest_phone: string;
  guest_name?: string;
  agent_name?: string;
  disposition: string;
  qa_score?: number;
  sentiment?: "positive" | "negative" | "neutral";
  has_transcript: boolean;
  transcription_status?: string;
  transcript_text?: string;
  ai_summary?: string;
  call_date?: string;
  created_at?: string;
  recording_url?: string | null;
  ai_next_action?: string | null;
  recommended_action?: {
    type: string;
    label: string;
    target_field: string;
    target: string;
    target_conversation_id?: string | null;
  } | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string) {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

function fmt(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function qaScoreClass(score?: number) {
  if (!score) return "";
  if (score >= 90) return "text-emerald-600 dark:text-emerald-400";
  if (score >= 70) return "text-amber-600 dark:text-amber-400";
  return "text-rose-600 dark:text-rose-400";
}

function qaBadgeStyle(score?: number): React.CSSProperties {
  if (!score) return { background: "var(--muted)", color: "var(--haip-fg-subtle)" };
  if (score >= 90) return { background: "rgba(16,185,129,0.1)", color: "#059669" };
  if (score >= 70) return { background: "rgba(245,158,11,0.1)", color: "#D97706" };
  return { background: "rgba(239,68,68,0.1)", color: "#DC2626" };
}

function SentimentIcon({ s }: { s?: string }) {
  if (s === "positive") return <TrendingUp size={12} className="text-emerald-500" />;
  if (s === "negative") return <TrendingDown size={12} className="text-rose-400" />;
  return <Minus size={12} style={{ color: "var(--haip-fg-subtle)" }} />;
}

function CallDirectionIcon({ call }: { call: Pick<CallItem, "direction" | "is_missed"> }) {
  if (call.is_missed) return <PhoneMissed size={11} className="text-rose-500" />;
  if (call.direction === "outbound") return <PhoneOutgoing size={11} className="text-blue-500" />;
  return <PhoneIncoming size={11} className="text-emerald-500" />;
}

function callDirectionLabel(call: Pick<CallItem, "direction" | "is_missed">): string {
  if (call.is_missed) return "Missed";
  return call.direction === "outbound" ? "Outgoing" : "Incoming";
}

// ─── Call row ─────────────────────────────────────────────────────────────────

function CallRow({ call, onClick }: { call: CallItem; onClick: () => void }) {
  const dt = call.started_at || call.created_at || "";
  const name = call.guest_name || "Unknown";
  const phoneToken = call.guest_phone || "";
  const snippet = call.transcript_text?.trim().slice(0, 120) ?? "";

  return (
    <button
      onClick={onClick}
      className="w-full text-left px-5 py-3 transition-colors duration-150 hover:bg-muted/50 group"
      style={{ borderBottom: "1px solid var(--haip-border)" }}
    >
      <div className="flex items-center gap-3">
        {/* Avatar initial, direction badge in the corner */}
        <div className="relative flex-shrink-0">
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold"
            style={{
              background: "color-mix(in srgb, var(--primary) 12%, transparent)",
              color: "var(--primary)",
            }}
          >
            {name[0].toUpperCase()}
          </div>
          <div
            className="absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full flex items-center justify-center"
            style={{ background: "var(--card, #fff)", border: "1px solid var(--haip-border)" }}
            title={callDirectionLabel(call)}
          >
            <CallDirectionIcon call={call} />
          </div>
        </div>

        {/* Left: name + phone token */}
        <div className="w-36 flex-shrink-0 min-w-0">
          <p className="text-sm font-medium truncate" style={{ color: "var(--haip-fg)" }}>{name}</p>
          <p className="text-[10px] tabular-nums" style={{ color: "var(--haip-fg-subtle)" }}>{phoneToken}</p>
        </div>

        {/* Center: transcript snippet */}
        <p className="flex-1 text-xs truncate hidden sm:block" style={{ color: "var(--haip-fg-subtle)" }}>
          {snippet
            || (call.transcription_status === "skipped_short_call" ? "Too short for AI analysis"
              : call.has_transcript ? "Transcript available" : "No transcript yet")}
        </p>

        {/* Right: QA badge + duration + time */}
        <div className="flex items-center gap-3 flex-shrink-0">
          {call.qa_score != null ? (
            <span
              className="text-xs font-bold tabular-nums px-2 py-0.5 rounded-full"
              style={qaBadgeStyle(call.qa_score)}
            >
              {call.qa_score}
            </span>
          ) : (
            <span className="text-[10px] rounded-full px-2 py-0.5" style={{ background: "var(--muted)", color: "var(--haip-fg-subtle)" }}>
              —
            </span>
          )}
          <SentimentIcon s={call.sentiment} />
          {call.duration_seconds > 0 && (
            <span className="text-[10px] tabular-nums hidden md:block" style={{ color: "var(--haip-fg-subtle)" }}>
              {fmt(call.duration_seconds)}
            </span>
          )}
          <span className="text-[10px] hidden sm:block" style={{ color: "var(--haip-fg-subtle)" }}>
            {dt ? timeAgo(dt) : "—"}
          </span>
          <ChevronRight size={13} className="transition-colors duration-150 group-hover:opacity-60" style={{ color: "var(--haip-fg-subtle)" }} />
        </div>
      </div>
    </button>
  );
}

// ─── Call slide-over ──────────────────────────────────────────────────────────

function CallSlideOver({ callId, onClose }: { callId: string; onClose: () => void }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { data: call, isLoading } = useQuery<CallItem>({
    queryKey: ["call-detail", callId],
    queryFn: () => api.get(`/calls/${callId}`).then(r => r.data),
    staleTime: 60_000,
  });

  // Mcube-disconnect + outbound-calling pass: same POST /calls/click-to-call
  // Inbox's GuestPanel/ConversationList use -- Vobiz (or whichever IVR is
  // active) rings the agent's registered mobile first, then bridges to the
  // guest. No audio in the browser.
  const clickToCall = useMutation({
    mutationFn: (guest_number: string) => api.post("/calls/click-to-call", { guest_number }),
    onSuccess: () => toast({ variant: "success", title: "Calling…", description: "Your phone will ring shortly." }),
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Could not start call";
      toast({ variant: "error", title: "Call failed", description: msg });
    },
  });

  // M5+ WS1/WS3: reuses the existing approve-and-queue endpoint
  // (conversations.py::approve_ai_draft) rather than a new one.
  const approveAndSendMutation = useMutation({
    mutationFn: ({ conversationId, messageId }: { conversationId: string; messageId: string }) =>
      api.post(`/conversations/${conversationId}/messages/${messageId}/approve`),
    onSuccess: () => {
      toast({ variant: "success", title: "Draft sent", description: "The WhatsApp reply is on its way." });
      queryClient.invalidateQueries({ queryKey: ["call-detail", callId] });
    },
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Could not send the draft";
      toast({ variant: "error", title: "Send failed", description: msg });
    },
  });

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />

      {/* Panel */}
      <div
        className="fixed right-0 top-0 h-full z-50 flex flex-col overflow-hidden"
        style={{
          width: "min(560px, 100vw)",
          background: "var(--haip-card)",
          borderLeft: "1px solid var(--haip-border)",
          boxShadow: "-8px 0 24px rgba(0,0,0,0.12)",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)" }}>
          <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>
            {isLoading ? "Loading…" : call?.guest_name || "Call detail"}
          </p>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center rounded-lg transition-colors duration-150 hover:bg-muted" style={{ color: "var(--haip-fg-subtle)" }}>
            <X size={15} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto haip-scrollbar p-5 space-y-5">
          {isLoading ? (
            <div className="space-y-4">
              {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
            </div>
          ) : !call ? (
            <p className="text-sm text-center pt-16" style={{ color: "var(--haip-fg-subtle)" }}>Call not found.</p>
          ) : (
            <>
              {/* Score hero — navy gradient with the QA score as the anchor,
                  per the prototype's .score-hero / .big-score */}
              <div
                className="flex items-center gap-[18px] rounded-lg px-[22px] py-[18px]"
                style={{
                  background: "linear-gradient(135deg, #0B1F3A 0%, #163458 100%)",
                  color: "#fff",
                }}
              >
                {call.qa_score != null ? (
                  <div
                    className="w-[84px] h-[84px] rounded-full flex items-center justify-center flex-shrink-0"
                    style={{
                      background: "rgba(20,184,166,0.15)",
                      border: "3px solid var(--haip-sidebar-accent)",
                      color: "var(--haip-sidebar-accent)",
                      fontFamily: "var(--font-display), sans-serif",
                      fontSize: 28,
                      fontWeight: 800,
                    }}
                  >
                    {call.qa_score}
                  </div>
                ) : (
                  <div
                    className="w-[84px] h-[84px] rounded-full flex items-center justify-center flex-shrink-0"
                    style={{ background: "rgba(255,255,255,0.08)", border: "3px solid rgba(255,255,255,0.15)" }}
                  >
                    <Phone size={26} style={{ color: "rgba(255,255,255,0.5)" }} />
                  </div>
                )}
                <div className="min-w-0">
                  <p className="text-[18px] font-bold truncate" style={{ fontFamily: "var(--font-display), sans-serif" }}>
                    {call.guest_name || "Unknown"}
                  </p>
                  <div className="flex items-center gap-2">
                    <p className="text-[13px] tabular-nums" style={{ color: "rgba(255,255,255,0.7)" }}>
                      {call.guest_phone}
                    </p>
                    {call.guest_phone && (
                      <button
                        type="button"
                        onClick={() => clickToCall.mutate(call.guest_phone)}
                        disabled={clickToCall.isPending}
                        title="Call via IVR"
                        className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold disabled:opacity-50"
                        style={{ background: "rgba(20,184,166,0.2)", color: "var(--haip-sidebar-accent)" }}
                      >
                        {clickToCall.isPending
                          ? <Loader2 size={11} className="animate-spin" />
                          : <Phone size={11} />}
                        Call
                      </button>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-2 text-[12px] flex-wrap" style={{ color: "rgba(255,255,255,0.6)" }}>
                    {call.duration_seconds > 0 && <span>{fmt(call.duration_seconds)}</span>}
                    {call.agent_name && <span>· {call.agent_name}</span>}
                    {call.direction && <span>· {call.direction}</span>}
                  </div>
                </div>
              </div>

              {/* Recording — native <audio> kept (real scrubbing/keyboard
                  support) but seated on the prototype's navy .wave surface
                  so it reads as part of the design rather than a raw
                  browser control floating on the page. */}
              {call.recording_url ? (
                <div
                  className="rounded-lg px-4 py-3"
                  style={{ background: "#0B1F3A" }}
                >
                  <p
                    className="text-[10px] font-bold uppercase tracking-[0.08em] mb-2"
                    style={{ color: "rgba(255,255,255,0.45)" }}
                  >
                    Recording
                  </p>
                  <audio
                    controls
                    className="w-full"
                    src={
                      call.recording_url.startsWith("/")
                        ? `${(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/api\/v1$/, "")}${call.recording_url}`
                        : call.recording_url
                    }
                  />
                </div>
              ) : (
                <div className="rounded-lg p-4 text-center" style={{ background: "var(--haip-surface)", border: "1px solid var(--haip-border)" }}>
                  <p className="text-xs" style={{ color: "var(--haip-fg-muted)" }}>Recording not yet available</p>
                </div>
              )}

              {/* AI Summary */}
              {call.ai_summary && (
                <div className="rounded-xl p-4" style={{ background: "color-mix(in srgb, var(--primary) 5%, transparent)", border: "1px solid color-mix(in srgb, var(--primary) 15%, transparent)" }}>
                  <p className="text-xs font-medium uppercase tracking-wider mb-2 flex items-center gap-1.5" style={{ color: "var(--primary)" }}>
                    <Sparkles size={11} /> AI Summary
                  </p>
                  <p className="text-sm leading-relaxed" style={{ color: "var(--haip-fg-2)" }}>{call.ai_summary}</p>
                  {call.ai_next_action && (
                    <p className="text-xs font-medium mt-2 pt-2" style={{ color: "var(--primary)", borderTop: "1px solid color-mix(in srgb, var(--primary) 15%, transparent)" }}>
                      → {call.ai_next_action}
                    </p>
                  )}
                  {call.recommended_action?.type === "send_whatsapp_draft" && call.recommended_action.target_conversation_id && (
                    <button
                      type="button"
                      onClick={() => approveAndSendMutation.mutate({
                        conversationId: call.recommended_action!.target_conversation_id!,
                        messageId: call.recommended_action!.target,
                      })}
                      disabled={approveAndSendMutation.isPending}
                      className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-teal-600 hover:bg-teal-700 disabled:opacity-60 text-white text-xs font-semibold rounded-lg transition-colors"
                    >
                      {approveAndSendMutation.isPending ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <MessageSquare size={12} />
                      )}
                      {call.recommended_action.label}
                    </button>
                  )}
                </div>
              )}

              {/* Transcript */}
              {call.transcript_text && (
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider mb-3" style={{ color: "var(--haip-fg-subtle)" }}>Transcript</p>
                  <div className="space-y-2 max-h-64 overflow-y-auto haip-scrollbar rounded-xl p-3" style={{ background: "var(--muted)" }}>
                    {call.transcript_text.split("\n").filter(Boolean).map((line, i) => {
                      const isAgent = line.toLowerCase().startsWith("agent:");
                      const isGuest = line.toLowerCase().startsWith("guest:");
                      return (
                        <p key={i} className="text-xs leading-relaxed" style={{ color: isAgent ? "var(--primary)" : isGuest ? "var(--haip-fg)" : "var(--haip-fg-subtle)" }}>
                          {line}
                        </p>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Disposition */}
              <div className="rounded-xl p-4" style={{ background: "var(--muted)" }}>
                <p className="text-xs font-medium uppercase tracking-wider mb-2" style={{ color: "var(--haip-fg-subtle)" }}>Outcome</p>
                <p className="text-sm font-medium capitalize" style={{ color: "var(--haip-fg)" }}>{call.disposition || "—"}</p>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

// ─── Dialer modal ───────────────────────────────────────────────────────────

const DIAL_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

// Dial pad only collects digits/*/# -- normalize to E.164 before sending so
// a bare "918179631737" or "8179631737" doesn't reach the backend as
// something Vobiz's Call API silently rejects. Mirrors the same "+91"
// convention used throughout the backend's own phone normalization.
function toE164In(raw: string): string {
  const trimmed = raw.trim();
  if (trimmed.startsWith("+")) return trimmed;
  const digits = trimmed.replace(/^0+/, "");
  if (digits.startsWith("91") && digits.length === 12) return `+${digits}`;
  return `+91${digits}`;
}

function DialerModal({ onClose }: { onClose: () => void }) {
  const { toast } = useToast();
  const [number, setNumber] = useState("");

  const call = useMutation({
    mutationFn: (guest_number: string) => api.post("/calls/click-to-call", { guest_number }),
    onSuccess: () => {
      toast({ variant: "success", title: "Calling…", description: "Your phone will ring shortly." });
      onClose();
    },
    onError: (err: any) => {
      // FastAPI validation errors (422) return `detail` as an array of
      // objects, not a string -- rendering that directly produced the
      // unhelpful generic fallback instead of the real reason.
      const raw = err?.response?.data?.detail;
      const msg = typeof raw === "string"
        ? raw
        : Array.isArray(raw)
          ? raw.map((e: any) => e?.msg ?? JSON.stringify(e)).join("; ")
          : err?.message || "Could not start call — check the network tab for details";
      toast({ variant: "error", title: "Call failed", description: msg });
    },
  });

  const press = (k: string) => setNumber(n => n + k);
  const backspace = () => setNumber(n => n.slice(0, -1));

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div
        className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[300px] rounded-2xl overflow-hidden"
        style={{ background: "var(--haip-card, #fff)", boxShadow: "0 20px 40px rgba(0,0,0,0.2)" }}
      >
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid var(--haip-border)" }}>
          <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>New call</p>
          <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded-lg hover:bg-muted" style={{ color: "var(--haip-fg-subtle)" }}>
            <X size={14} />
          </button>
        </div>

        <div className="p-5 flex flex-col items-center gap-4">
          <div className="w-full flex items-center justify-center gap-2">
            <input
              value={number}
              onChange={e => setNumber(e.target.value.replace(/[^\d+*#]/g, ""))}
              placeholder="+91 98765 43210"
              autoFocus
              className="flex-1 text-center text-lg font-semibold tabular-nums px-2 py-2 rounded-xl outline-none"
              style={{ color: "var(--haip-fg)", background: "var(--muted)" }}
            />
            {number && (
              <button onClick={backspace} className="w-9 h-9 flex items-center justify-center rounded-xl hover:bg-muted flex-shrink-0" style={{ color: "var(--haip-fg-muted)" }}>
                <Delete size={16} />
              </button>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            {DIAL_KEYS.map(k => (
              <button
                key={k}
                onClick={() => press(k)}
                className="w-14 h-14 rounded-full text-lg font-semibold transition-colors duration-150"
                style={{ background: "var(--muted)", color: "var(--haip-fg)" }}
              >
                {k}
              </button>
            ))}
          </div>

          <button
            onClick={() => number.trim() && call.mutate(toE164In(number))}
            disabled={call.isPending || !number.trim()}
            className="w-14 h-14 rounded-full flex items-center justify-center text-white disabled:opacity-50 mt-1"
            style={{ background: "var(--primary)" }}
          >
            {call.isPending ? <Loader2 size={20} className="animate-spin" /> : <PhoneCall size={20} />}
          </button>
        </div>
      </div>
    </>
  );
}

// ─── Filters panel content — shared between the desktop inline panel and
// the mobile bottom sheet so there's one definition of these controls. ────

function CallsFiltersContent({
  filters, setFilters, hasFilters, resetFilters, layout,
}: {
  filters: CallFilters;
  setFilters: (f: Partial<CallFilters>) => void;
  hasFilters: boolean;
  resetFilters: () => void;
  layout: "row" | "column";
}) {
  return (
    <div className={layout === "row" ? "flex flex-wrap items-center gap-2" : "flex flex-col gap-2.5"}>
      <select
        value={filters.disposition ?? ""}
        onChange={e => setFilters({ disposition: e.target.value as any })}
        className="text-xs rounded-lg px-2.5 py-1.5 focus:outline-none"
        style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
      >
        <option value="">All dispositions</option>
        {["pending","qualified","booked","lost","spam","callback"].map(d => (
          <option key={d} value={d} className="capitalize">{d}</option>
        ))}
      </select>
      <div className={cn("flex items-center gap-1.5", layout === "column" && "flex-wrap")}>
        <Calendar size={12} style={{ color: "var(--haip-fg-subtle)" }} />
        <input type="date" value={filters.dateFrom ?? ""} onChange={e => setFilters({ dateFrom: e.target.value })}
          className="text-xs rounded-lg px-2 py-1.5 focus:outline-none"
          style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }} />
        <span className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>–</span>
        <input type="date" value={filters.dateTo ?? ""} onChange={e => setFilters({ dateTo: e.target.value })}
          className="text-xs rounded-lg px-2 py-1.5 focus:outline-none"
          style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }} />
      </div>
      {hasFilters && (
        <button onClick={resetFilters} className={cn("text-xs font-medium flex items-center gap-1", layout === "row" && "ml-auto")} style={{ color: "var(--haip-red)" }}>
          <X size={11} /> Clear
        </button>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CallsPage() {
  const queryClient = useQueryClient();
  const { filters, setFilters, resetFilters, wrapUpQueue, dismissWrapUp } = useCallsStore();
  const [showFilters, setShowFilters] = useState(false);
  const [showMobileFilters, setShowMobileFilters] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [showDialer, setShowDialer] = useState(false);
  const [search, setSearch] = useState("");
  const [activeCallId, setActiveCallId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [callType, setCallType] = useState<"all" | "missed" | "incoming" | "outgoing">("all");
  const pageSize = 20;

  const { data, isLoading, isError, error } = useQuery<{ items: CallItem[]; total: number }>({
    queryKey: ["calls", filters, page, callType],
    queryFn: () => {
      const params: Record<string, string | number | boolean> = { page, limit: pageSize };
      if (filters.disposition) params.disposition = filters.disposition;
      if (filters.dateFrom)    params.date_from = filters.dateFrom;
      if (filters.dateTo)      params.date_to = filters.dateTo;
      if (filters.agentId)     params.agent_id = filters.agentId;
      if (callType === "missed") params.missed = true;
      if (callType === "incoming") { params.direction = "inbound"; params.missed = false; }
      if (callType === "outgoing") params.direction = "outbound";
      return api.get("/calls", { params }).then(r => ({
        items: r.data?.items ?? r.data ?? [],
        total: r.data?.total ?? (r.data?.items ?? r.data ?? []).length,
      }));
    },
    staleTime: 30_000,
  });
  const calls = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => { setPage(1); }, [filters, callType]);

  const filtered = search.trim()
    ? calls.filter(c =>
        c.guest_phone?.includes(search) ||
        c.guest_name?.toLowerCase().includes(search.toLowerCase()) ||
        c.agent_name?.toLowerCase().includes(search.toLowerCase())
      )
    : calls;

  const hasFilters = Object.values(filters).some(Boolean);

  return (
    <div className="h-full flex flex-col bg-background">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="px-5 py-4 flex-shrink-0" style={{ borderBottom: "1px solid var(--haip-border)" }}>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h1
              className="text-[22px] font-bold tracking-tight"
              style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display), sans-serif" }}
            >
              Calls
            </h1>
            <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-muted)" }}>
              {search.trim()
                ? `${filtered.length} of ${calls.length} on this page match`
                : `${total} call${total !== 1 ? "s" : ""}`} · click row to inspect
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowDialer(true)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors duration-150"
              style={{ background: "var(--haip-sidebar, #0B1F3A)", color: "#fff" }}
            >
              <PhoneCall size={12} /> Dial
            </button>
            <button
              onClick={() => setShowFilters(v => !v)}
              className={cn("hidden md:flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors duration-150 font-medium")}
              style={hasFilters
                ? { background: "color-mix(in srgb, var(--primary) 8%, transparent)", borderColor: "var(--primary)", color: "var(--primary)" }
                : { background: "transparent", borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)" }}
            >
              <Filter size={12} /> Filters
              {hasFilters && <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--primary)" }} />}
            </button>
            <MobileFilterTrigger onClick={() => setShowMobileFilters(true)} hasActiveFilters={hasFilters} />
            <button
              onClick={() => setShowUpload(true)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors duration-150"
              style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
            >
              <Upload size={12} /> Upload
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--haip-fg-subtle)" }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by guest, phone, or agent…"
            className="w-full pl-8 pr-4 py-2 text-sm rounded-md focus:outline-none transition-shadow"
            style={{ background: "var(--input-bg)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
          />
        </div>

        {/* Call-type chips */}
        <div className="flex items-center gap-1.5 mt-2.5">
          {([
            ["all", "All"],
            ["missed", "Missed"],
            ["incoming", "Incoming"],
            ["outgoing", "Outgoing"],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setCallType(key)}
              className="text-xs px-2.5 py-1 rounded-full font-medium border transition-colors duration-150"
              style={callType === key
                ? { background: "color-mix(in srgb, var(--primary) 10%, transparent)", borderColor: "var(--primary)", color: "var(--primary)" }
                : { background: "transparent", borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)" }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Filters — desktop inline panel */}
        {showFilters && (
          <div className="hidden md:block mt-3 p-3 rounded-xl" style={{ background: "var(--muted)" }}>
            <CallsFiltersContent filters={filters} setFilters={setFilters} hasFilters={hasFilters} resetFilters={resetFilters} layout="row" />
          </div>
        )}

        {/* Wrap-up badges */}
        {wrapUpQueue.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {wrapUpQueue.map(callId => (
              <div key={callId} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium"
                style={{ background: "color-mix(in srgb, var(--primary) 8%, transparent)", border: "1px solid color-mix(in srgb, var(--primary) 20%, transparent)", color: "var(--primary)" }}>
                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "var(--primary)" }} />
                Wrap-up ready
                <button onClick={() => { setActiveCallId(callId); dismissWrapUp(callId); }} className="underline ml-0.5">View</button>
                <button onClick={() => dismissWrapUp(callId)} className="ml-1 opacity-60 hover:opacity-100"><X size={10} /></button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Table header ───────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 px-5 py-2 grid items-center"
        style={{
          borderBottom: "1px solid var(--haip-border)",
          gridTemplateColumns: "36px 144px 1fr auto",
          gap: "12px",
        }}>
        {["", "Guest", "Transcript", "Score / Time"].map((h, i) => (
          <span key={i} className="text-[10px] font-medium uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>{h}</span>
        ))}
      </div>

      {/* ── Call list ──────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto haip-scrollbar">
        {isLoading ? (
          <div className="divide-y" style={{ borderColor: "var(--haip-border)" }}>
            {[...Array(6)].map((_, i) => (
              <div key={i} className="px-5 py-3 flex items-center gap-3">
                <Skeleton className="w-9 h-9 rounded-full flex-shrink-0" />
                <div className="flex-1 space-y-1.5"><Skeleton className="h-3.5 w-40" /><Skeleton className="h-3 w-24" /></div>
                <Skeleton className="w-12 h-5 rounded-full" />
              </div>
            ))}
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center py-24 text-center gap-2">
            <AlertCircle size={28} className="text-rose-500" />
            <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>Couldn't load calls</p>
            <p className="text-xs max-w-sm" style={{ color: "var(--haip-fg-subtle)" }}>
              {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
                || (error as Error)?.message
                || "Unknown error — check the browser console or try refreshing."}
            </p>
          </div>
        ) : filtered.length === 0 ? (
          callType !== "all" || search.trim() ? (
            // A chip/search filter narrowed a non-empty call log down to
            // zero rows -- that's not "no IVR connected", it's just "no
            // matches". EmptyCalls' onboarding card was showing regardless
            // of which case this was, telling an already-connected tenant
            // to go connect their IVR provider.
            <div className="flex flex-col items-center justify-center py-24 text-center gap-1.5">
              <PhoneMissed size={26} style={{ color: "var(--haip-fg-subtle)" }} />
              <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>
                No {callType !== "all" ? callType : ""} calls{search.trim() ? " match your search" : ""}
              </p>
              {(callType !== "all" || search.trim()) && (
                <button
                  onClick={() => { setCallType("all"); setSearch(""); }}
                  className="text-xs font-medium mt-1"
                  style={{ color: "var(--primary)" }}
                >
                  Clear filters
                </button>
              )}
            </div>
          ) : (
            <EmptyCalls />
          )
        ) : (
          filtered.map(call => (
            <CallRow key={call.id} call={call} onClick={() => setActiveCallId(call.id)} />
          ))
        )}
      </div>

      {/* ── Pagination ─────────────────────────────────────────────────────── */}
      {!isLoading && !isError && totalPages > 1 && (
        <div className="flex items-center justify-between px-5 py-3 flex-shrink-0" style={{ borderTop: "1px solid var(--haip-border)" }}>
          <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>
            Page {page} of {totalPages}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="text-xs px-3 py-1.5 rounded-lg border font-medium disabled:opacity-40"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)" }}
            >
              Previous
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="text-xs px-3 py-1.5 rounded-lg border font-medium disabled:opacity-40"
              style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg-muted)" }}
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* ── Slide-over ─────────────────────────────────────────────────────── */}
      {activeCallId && (
        <CallSlideOver callId={activeCallId} onClose={() => setActiveCallId(null)} />
      )}

      {/* ── Upload modal ────────────────────────────────────────────────────── */}
      {showUpload && (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onSuccess={() => { queryClient.invalidateQueries({ queryKey: ["calls"] }); setShowUpload(false); }}
        />
      )}

      {/* ── Dialer modal ───────────────────────────────────────────────────── */}
      {showDialer && <DialerModal onClose={() => setShowDialer(false)} />}

      {/* ── Filters — mobile bottom sheet ───────────────────────────────────── */}
      <MobileFilterSheet open={showMobileFilters} onOpenChange={setShowMobileFilters} hasActiveFilters={hasFilters}>
        <CallsFiltersContent filters={filters} setFilters={setFilters} hasFilters={hasFilters} resetFilters={resetFilters} layout="column" />
      </MobileFilterSheet>
    </div>
  );
}
