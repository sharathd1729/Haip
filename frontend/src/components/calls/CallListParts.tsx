"use client";
// Calls list pieces: types, formatting helpers, summary tiles and the call
// row (direction pinned to the avatar, guest's channels by the name, inline
// Call back / play). Used by app/dashboard/calls/page.tsx.
import { Phone, Loader2, PhoneIncoming, PhoneOutgoing, PhoneMissed, Play, CheckCircle2 } from "@/lib/icons";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { ChannelBadges } from "@/components/inbox/ChannelBadges";
import { OUTCOMES } from "@/components/calls/CallDetailPanel";
import { SendQuoteButton } from "@/components/quotes/SendQuoteButton";
import type { GuestChannel } from "@/store/inbox";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CallItem {
  id: string;
  direction: "inbound" | "outbound";
  is_missed?: boolean;
  called_back?: boolean | null;
  called_back_at?: string | null;
  duration_seconds: number;
  guest_phone: string;
  guest_name?: string | null;
  agent_name?: string | null;
  disposition?: string | null;
  qa_score?: number | null;
  created_at?: string | null;
  started_at?: string | null;
  guest_channels?: GuestChannel[];
}

export interface CallsSummary {
  total: number;
  inbound: number;
  outbound: number;
  missed_not_called_back: number;
  oldest_missed_at: string | null;
  answer_rate: number | null;
  avg_answered_seconds: number | null;
  avg_qa_score: number | null;
  avg_qa_change: number | null;
}

export type Tab = "callback" | "all" | "incoming" | "outgoing";

export const RANGES = [
  { value: "today", label: "Today" },
  { value: "yesterday", label: "Yesterday" },
  { value: "last_7d", label: "Last 7 days" },
  { value: "last_14d", label: "Last 14 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function fmt(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function ago(iso: string) {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `${Math.max(1, m)}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

function gap(fromIso: string, toIso: string) {
  const m = Math.max(0, Math.round((new Date(toIso).getTime() - new Date(fromIso).getTime()) / 60000));
  return m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
}

export function dayLabel(iso: string) {
  const d = new Date(iso);
  const today = new Date();
  const yday = new Date(); yday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yday.toDateString()) return "Yesterday";
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

function timeOf(iso: string) {
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

function outcomeMeta(value?: string | null) {
  return OUTCOMES.find(o => o.value === value);
}

// ─── Summary tiles ────────────────────────────────────────────────────────────

// Each tile opens the list it summarises: a tab on this page, or the QA page.
export function SummaryTiles({
  s, rangeLabel, onPick,
}: { s?: CallsSummary; rangeLabel: string; onPick: (tab: Tab) => void }) {
  const tiles: { label: string; value: string; note: string; tone: string; dot: string; tab?: Tab; href?: string }[] = [
  { label: `Calls · ${rangeLabel.toLowerCase()}`, value: s ? String(s.total) : "–", note: s ? `${s.inbound} in · ${s.outbound} out` : "", tone: "text-[var(--haip-fg)] ", dot: "bg-[var(--haip-border-strong)]", tab: "all" },
  { label: "Missed · not called back", value: s ? String(s.missed_not_called_back) : "–", note: s?.oldest_missed_at ? `oldest ${ago(s.oldest_missed_at)}` : "all returned", tone: "text-[var(--haip-status-danger-fg)]", dot: "bg-red-600", tab: "callback" },
  { label: "Answered", value: s?.answer_rate != null ? `${s.answer_rate}%` : "–", note: "of incoming", tone: "text-[var(--haip-status-success-fg)]", dot: "bg-[var(--haip-status-success-fg)]", tab: "incoming" },
  { label: "Avg call length", value: s?.avg_answered_seconds != null ? fmt(s.avg_answered_seconds) : "–", note: "answered calls", tone: "text-primary", dot: "bg-primary", tab: "incoming" },
  {
  label: "Avg QA score", value: s?.avg_qa_score != null ? String(Math.round(s.avg_qa_score)) : "–",
  note: s?.avg_qa_change != null ? `${s.avg_qa_change >= 0 ? "▲" : "▼"} ${Math.abs(s.avg_qa_change)} vs previous` : "",
  tone: "text-violet-700", dot: "bg-violet-600", href: "/dashboard/qa",
  },
  ];
  return (
  <div className="flex gap-2.5 overflow-x-auto haip-scrollbar-x pb-1 lg:grid lg:grid-cols-5 lg:overflow-visible">
  {tiles.map(t => {
  const cls = "haip-card flex-shrink-0 min-w-[150px] px-4 py-3 text-left block cursor-pointer transition-shadow hover:shadow-md outline-none focus-visible:ring-2 focus-visible:ring-primary";
  const body = (
  <>
  <span className="flex items-center gap-1.5 text-xs font-semibold truncate" style={{ color: "var(--haip-fg-subtle)" }}>
  <span className={cn("w-2 h-2 rounded-full flex-shrink-0", t.dot)} />{t.label}
  </span>
  <span className={cn("block text-2xl font-bold tabular-nums mt-1", t.tone)} style={{ fontFamily: "var(--font-display)" }}>{t.value}</span>
  <span className="block text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>{t.note || " "}</span>
  </>
  );
  return t.href
  ? <Link key={t.label} href={t.href} className={cls}>{body}</Link>
  : <button key={t.label} type="button" onClick={() => t.tab && onPick(t.tab)} className={cls}>{body}</button>;
  })}
  </div>
  );
}

// ─── Row ──────────────────────────────────────────────────────────────────────

function DirectionAvatar({ call }: { call: CallItem }) {
  const name = call.guest_name || call.guest_phone || "?";
  const missed = !!call.is_missed;
  const Icon = missed ? PhoneMissed : call.direction === "outbound" ? PhoneOutgoing : PhoneIncoming;
  const color = missed ? "var(--haip-status-danger-fg)" : call.direction === "outbound" ? "var(--haip-status-info-fg)" : "var(--haip-status-success-fg)";
  return (
  <span className="relative flex-shrink-0">
  <span className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold bg-primary/10 text-primary ">
  {name[0]?.toUpperCase()}
  </span>
  <span title={missed ? "Missed" : call.direction === "outbound" ? "Outgoing" : "Incoming"}
  className="absolute -bottom-0.5 -right-0.5 w-[18px] h-[18px] rounded-full flex items-center justify-center text-[var(--haip-card)]"
  style={{ background: color, boxShadow: "0 0 0 2px var(--haip-card)" }}>
  <Icon size={10} />
  </span>
  </span>
  );
}

export function CallRow({
  call, selected, onSelect, onPlay, onCallBack, calling,
}: {
  call: CallItem; selected: boolean; onSelect: () => void; onPlay: () => void;
  onCallBack: () => void; calling: boolean;
}) {
  const when = call.created_at || call.started_at || "";
  const outcome = outcomeMeta(call.disposition);
  const score = call.qa_score != null && call.qa_score > 0 ? Math.round(call.qa_score) : null;
  return (
  <div
  role="button" tabIndex={0} onClick={onSelect} onKeyDown={e => { if (e.key === "Enter") onSelect(); }}
  className={cn("flex items-center gap-3 px-4 py-3 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
  selected ? "bg-primary/10 " : "hover:bg-[color:var(--muted)]")}
  style={{ borderBottom: "1px solid var(--haip-border)" }}
  >
  <DirectionAvatar call={call} />
  <div className="flex-1 min-w-0">
  <div className="flex items-center gap-1.5 min-w-0">
  <span className="text-sm font-bold truncate" style={{ color: "var(--haip-fg)" }}>{call.guest_name || call.guest_phone || "Unknown caller"}</span>
  <ChannelBadges channels={call.guest_channels} size={13} />
  </div>
  <p className="text-xs mt-0.5 truncate" style={{ color: "var(--haip-fg-subtle)" }}>
  {call.is_missed ? "Unanswered" : call.agent_name || "—"}{when ? ` · ${timeOf(when)}` : ""}
  </p>
  {/* Phone: status under the meta line */}
  <div className="sm:hidden mt-1">
  {call.is_missed ? (
  call.called_back
  ? <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]">Called back{call.called_back_at && when ? ` · ${gap(when, call.called_back_at)}` : ""}</span>
  : <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]">Not called back</span>
  ) : outcome ? (
  <span className={cn("text-[11px] font-semibold px-2 py-0.5 rounded-full border", outcome.tone)}>{outcome.label}</span>
  ) : null}
  </div>
  </div>

  <div className="flex items-center gap-2.5 flex-shrink-0">
  {/* Quote from the call row; a missed call with no lead opens with its number ready for "Add as new lead". */}
  <SendQuoteButton iconOnlyBelowSm label="Quote" className="min-h-9 px-2.5 text-xs"
    args={{ callId: call.id, from: "calls", name: call.guest_name || null }} />
  {call.is_missed ? (
  <>
  {call.called_back ? (
  <span className="hidden sm:inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]">
  <CheckCircle2 size={11} /> Called back{call.called_back_at && when ? ` · ${gap(when, call.called_back_at)}` : ""}
  </span>
  ) : (
  <>
  <span className="hidden sm:inline text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]">Not called back</span>
  <button type="button" onClick={e => { e.stopPropagation(); onCallBack(); }} disabled={calling || !call.guest_phone}
  className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60">
  {calling ? <Loader2 size={12} className="animate-spin" /> : <Phone size={12} />} Call back
  </button>
  </>
  )}
  </>
  ) : (
  <>
  {call.duration_seconds > 0 && (
  <button type="button" onClick={e => { e.stopPropagation(); onPlay(); }} title="Play recording" aria-label="Play recording"
  className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 text-xs font-semibold tabular-nums px-2 py-1 rounded-lg hover:bg-[color:var(--muted)] sm:min-h-0 sm:min-w-0 sm:justify-start"
  style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>
  <span className="w-6 h-6 rounded-full flex items-center justify-center" style={{ background: "var(--muted)" }}>
  <Play size={11} className="text-primary" />
  </span>
  <span className="hidden sm:inline">{fmt(call.duration_seconds)}</span>
  </button>
  )}
  {outcome && <span className={cn("hidden sm:inline text-[11px] font-semibold px-2 py-0.5 rounded-full border", outcome.tone)}>{outcome.label}</span>}
  {score != null && (
  <span className={cn("text-xs font-extrabold tabular-nums px-2 py-0.5 rounded-full",
  score >= 85 ? "bg-[var(--haip-status-success-bg)] text-[var(--haip-status-success-fg)]" : score >= 70 ? "bg-[var(--haip-status-warning-bg)] text-[var(--haip-status-warning-fg)]" : "bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]")}>
  {score}
  </span>
  )}
  </>
  )}
  </div>
  </div>
  );
}
