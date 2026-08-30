"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { MessageSquare, PhoneMissed, Inbox, Clock, AlertCircle, RefreshCw, ChevronRight, Phone, Mail, AtSign, Sparkles, Zap } from "@/lib/icons";
import { UserCheck } from "lucide-react";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

interface Contact { type: string; value: string }
interface Lead {
  guest_id?: string | null;
  name: string;
  phone?: string | null;
  contacts: Contact[];
  has_contact: boolean;
  inquiry_id?: string | null;
  source?: string | null;
  check_in?: string | null;
  check_out?: string | null;
  adults?: number | null;
  children?: number | null;
  occasion?: string | null;
  ai_summary?: string | null;
}
interface Row {
  conversation_id?: string | null;
  call_id?: string;
  task_id?: string;
  channel?: string;
  last_message?: string;
  body?: string;
  title?: string;
  from_number?: string;
  last_message_at?: string | null;
  received_at?: string | null;
  missed_at?: string | null;
  shared_at?: string | null;
  due_date?: string | null;
  waiting_minutes?: number | null;
  shared?: Contact[];
  lead: Lead;
}
interface Worklist {
  window_hours: number;
  counts: Record<string, number>;
  truncated: Record<string, boolean>;
  section_limit: number;
  scope: string;
  awaiting_reply: Row[];
  missed_calls: Row[];
  shared_details: Row[];
  new_dms: Row[];
  overdue_followups: Row[];
}
interface BriefingFlag { type: "quick_win" | "coverage_gap" | "pattern"; text: string }
interface Briefing { available: boolean; narrative?: string; flags?: BriefingFlag[]; generated_at?: string }

// Real semantic tokens (--haip-red/--haip-amber) exist for two of these;
// the rest follow this file's own established "var(--token, #fallback)"
// pattern (see DeltaBadge in dashboard/page.tsx) for tones globals.css
// doesn't define yet.
const SECTIONS = [
  {
    key: "awaiting_reply",
    label: "Waiting on us",
    blurb: "They messaged last and nobody has replied",
    icon: <MessageSquare size={15} />,
    color: "var(--haip-red, #dc2626)",
  },
  {
    key: "missed_calls",
    label: "Missed calls",
    blurb: "Came in, nobody picked up, not yet called back",
    icon: <PhoneMissed size={15} />,
    color: "var(--haip-orange, #c2540a)",
  },
  {
    key: "shared_details",
    label: "Shared their details",
    blurb: "Gave us a phone number or email — high intent",
    icon: <UserCheck size={15} />,
    color: "var(--primary)",
  },
  {
    key: "new_dms",
    label: "New messages",
    blurb: "Everything that came in",
    icon: <Inbox size={15} />,
    color: "var(--haip-blue, #2563eb)",
  },
  {
    key: "overdue_followups",
    label: "Overdue follow-ups",
    blurb: "Tasks past their due date",
    icon: <Clock size={15} />,
    color: "var(--haip-amber, #d97706)",
  },
] as const;

function waitLabel(mins?: number | null) {
  if (mins == null) return null;
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function whenOf(r: Row) {
  const raw = r.last_message_at || r.received_at || r.missed_at || r.shared_at || r.due_date;
  if (!raw) return "";
  const d = new Date(raw);
  return isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function ContactChips({ lead }: { lead: Lead }) {
  const items: { icon: React.ReactNode; value: string }[] = [];
  const seen = new Set<string>();
  for (const c of lead.contacts ?? []) {
    if (seen.has(c.value)) continue;
    seen.add(c.value);
    items.push({
      icon: c.type === "email" ? <Mail size={10} /> : <Phone size={10} />,
      value: c.value,
    });
  }
  if (!items.length && lead.phone) items.push({ icon: <Phone size={10} />, value: lead.phone });
  if (!items.length) {
    return <span className="text-[11px] italic" style={{ color: "var(--haip-fg-subtle)" }}>No contact details yet</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map(i => (
        <span
          key={i.value}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium"
          style={{ background: "var(--muted)", color: "var(--haip-fg)" }}
        >
          {i.icon}{i.value}
        </span>
      ))}
    </div>
  );
}

function LeadRow({ row, sectionKey }: { row: Row; sectionKey: string }) {
  const router = useRouter();
  const lead = row.lead;
  const text = row.last_message || row.body || row.title || (row.from_number ? `Called from ${row.from_number}` : "");
  const stay = [
    lead.check_in && lead.check_out ? `${lead.check_in} → ${lead.check_out}` : null,
    lead.adults ? `${lead.adults} adult${lead.adults > 1 ? "s" : ""}${lead.children ? ` + ${lead.children}` : ""}` : null,
    lead.occasion || null,
  ].filter(Boolean);

  const open = () => {
    if (row.conversation_id) router.push(`/dashboard/inbox?conversation=${row.conversation_id}`);
    else if (lead.inquiry_id) router.push(`/dashboard/leads/${lead.inquiry_id}`);
    else if (row.call_id) router.push(`/dashboard/calls/${row.call_id}`);
  };

  return (
    <div className="px-4 py-3 transition-colors last:border-0" style={{ borderBottom: "1px solid var(--haip-border)" }}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>{lead.name}</p>
            {row.channel && (
              <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>
                {row.channel === "instagram" ? <AtSign size={10} /> : <MessageSquare size={10} />}
                {row.channel}
              </span>
            )}
            {lead.source && (
              <span className="text-[10px]" style={{ color: "var(--haip-fg-subtle)" }}>via {lead.source.replace(/_/g, " ")}</span>
            )}
            {sectionKey === "awaiting_reply" && row.waiting_minutes != null && (
              <span
                className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                style={row.waiting_minutes > 240
                  ? { background: "color-mix(in srgb, var(--haip-red, #dc2626) 12%, transparent)", color: "var(--haip-red, #dc2626)" }
                  : { background: "color-mix(in srgb, var(--haip-amber, #d97706) 14%, transparent)", color: "var(--haip-amber, #d97706)" }}
              >
                waiting {waitLabel(row.waiting_minutes)}
              </span>
            )}
          </div>

          {text && <p className="text-xs mt-1 line-clamp-2" style={{ color: "var(--haip-fg-muted)" }}>{text}</p>}

          {/* What the agent needs before making contact */}
          <div className="mt-1.5 space-y-1">
            <ContactChips lead={lead} />
            {!!stay.length && (
              <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>{stay.join(" · ")}</p>
            )}
            {lead.ai_summary && (
              <p className="text-[11px] italic line-clamp-2" style={{ color: "var(--haip-fg-subtle)" }}>{lead.ai_summary}</p>
            )}
          </div>
        </div>

        <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
          <span className="text-[10px] whitespace-nowrap" style={{ color: "var(--haip-fg-subtle)" }}>{whenOf(row)}</span>
          <button
            onClick={open}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold transition-colors"
            style={{ background: "var(--haip-card)", border: "1.5px solid var(--haip-border)", color: "var(--haip-fg-2, var(--haip-fg))" }}
          >
            Open <ChevronRight size={11} />
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── AI Daily Briefing ─────────────────────────────────────────────────────

function AiBriefing() {
  const { data } = useQuery<Briefing>({
    queryKey: ["worklist-briefing"],
    queryFn: () => api.get("/worklist/briefing").then(r => r.data),
    // Not yet generated -- poll briefly until the async task lands. Once
    // available it's cached server-side for ~30 min, so stop polling.
    refetchInterval: (query) => (query.state.data?.available ? false : 8000),
    staleTime: 5 * 60_000,
  });

  if (!data?.available || !data.narrative) return null;

  return (
    <div
      className="p-4 rounded-xl mb-1"
      style={{ background: "var(--haip-card)", border: "1.5px dashed var(--haip-iris, #5b5bce)" }}
    >
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ background: "color-mix(in srgb, var(--haip-iris, #5b5bce) 12%, transparent)", color: "var(--haip-iris, #5b5bce)" }}
        >
          <Sparkles size={14} />
        </div>
        <div>
          <p className="text-[13px] font-bold" style={{ color: "var(--haip-iris, #5b5bce)" }}>Today's Briefing</p>
          <p className="text-[10.5px]" style={{ color: "var(--haip-fg-subtle)" }}>Patterns across everyone waiting on you right now</p>
        </div>
      </div>
      <p className="text-[12.5px] leading-relaxed mb-2.5" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>{data.narrative}</p>
      {!!data.flags?.length && (
        <div className="flex flex-col gap-1.5">
          {data.flags.map((f, i) => (
            <div key={i} className="flex items-start gap-2 text-[11.5px]" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>
              {f.type === "quick_win" ? <Zap size={13} style={{ color: "var(--haip-iris, #5b5bce)", marginTop: 1, flexShrink: 0 }} />
                : <Clock size={13} style={{ color: "var(--haip-iris, #5b5bce)", marginTop: 1, flexShrink: 0 }} />}
              <span>{f.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const RANGES = [
  { key: "5h",     label: "Last 5 hours",  hours: 5 },
  { key: "10h",    label: "Last 10 hours", hours: 10 },
  { key: "20h",    label: "Last 20 hours", hours: 20 },
  { key: "24h",    label: "Last 24 hours", hours: 24 },
  { key: "2d",     label: "Last 2 days",   hours: 48 },
  { key: "7d",     label: "Last 7 days",   hours: 168 },
  { key: "all",    label: "All time",      hours: 0 },
  { key: "custom", label: "Custom dates…", hours: null },
] as const;

function todayISO() {
  return new Date().toISOString().split("T")[0];
}

export default function WorklistPage() {
  const [range, setRange] = useState<string>("24h");
  const [from, setFrom] = useState(todayISO());
  const [to, setTo] = useState(todayISO());
  const [active, setActive] = useState<string>("awaiting_reply");
  // Rows fetched beyond the first page, keyed by section -- reset whenever
  // the active section or time window changes so an old page never lingers
  // under a different filter.
  const [extraRows, setExtraRows] = useState<Row[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const isCustom = range === "custom";
  const preset = RANGES.find(r => r.key === range);
  // hours=0 is the explicit "all time" signal the API understands.
  const params = isCustom
    ? { date_from: from, date_to: to }
    : { hours: preset?.hours ?? 24 };

  const { data, isLoading, isError, refetch, isFetching } = useQuery<Worklist>({
    queryKey: ["worklist", range, isCustom ? from : null, isCustom ? to : null],
    queryFn: () => api.get("/worklist", { params }).then(r => r.data),
    retry: 1,
    refetchOnWindowFocus: true,
    enabled: !isCustom || (!!from && !!to && from <= to),
  });

  const baseRows = (data?.[active as keyof Worklist] as Row[] | undefined) ?? [];
  const rows = [...baseRows, ...extraRows];
  const section = SECTIONS.find(s => s.key === active)!;
  const totalForSection = data?.counts?.[active] ?? 0;
  const canLoadMore = rows.length < totalForSection;

  const changeSection = (key: string) => {
    setActive(key);
    setExtraRows([]);
  };

  const loadMore = async () => {
    setIsLoadingMore(true);
    try {
      const resp = await api.get(`/worklist/section/${active}`, {
        params: { ...params, offset: rows.length, limit: data?.section_limit ?? 50 },
      });
      setExtraRows(prev => [...prev, ...(resp.data.rows as Row[])]);
    } finally {
      setIsLoadingMore(false);
    }
  };

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      <div className="px-6 py-5 flex-shrink-0" style={{ background: "var(--haip-card)", borderBottom: "1px solid var(--haip-border)" }}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="haip-page-title">Today</h1>
            <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              Everyone waiting on a reply, in the order they should be dealt with.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <select
              value={range}
              onChange={e => { setRange(e.target.value); setExtraRows([]); }}
              className="px-3 py-1.5 rounded-lg text-xs"
              style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
            >
              {RANGES.map(r => (
                <option key={r.key} value={r.key}>{r.label}</option>
              ))}
            </select>

            {isCustom && (
              <div className="flex items-center gap-1.5">
                <input
                  type="date"
                  value={from}
                  max={to || undefined}
                  onChange={e => { setFrom(e.target.value); setExtraRows([]); }}
                  className="px-2 py-1.5 rounded-lg text-xs"
                  style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
                />
                <span className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>→</span>
                <input
                  type="date"
                  value={to}
                  min={from || undefined}
                  onChange={e => { setTo(e.target.value); setExtraRows([]); }}
                  className="px-2 py-1.5 rounded-lg text-xs"
                  style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
                />
              </div>
            )}

            <button
              onClick={() => refetch()}
              title="Refresh"
              className="p-2 transition-colors"
              style={{ color: "var(--haip-fg-subtle)" }}
            >
              <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 p-6 space-y-4">
        <div className="max-w-4xl mx-auto space-y-4 w-full">
          <AiBriefing />

          {/* Infographic hero: 5 real stat cards, doubling as the section switcher */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
            {SECTIONS.map(s => {
              const n = data?.counts?.[s.key] ?? 0;
              const isActive = active === s.key;
              const isZero = n === 0;
              return (
                <button
                  key={s.key}
                  onClick={() => changeSection(s.key)}
                  className="rounded-xl p-3.5 text-left transition-transform hover:-translate-y-0.5"
                  style={{
                    background: "var(--haip-card)",
                    border: isActive ? `1.5px solid ${s.color}` : "1.5px solid var(--haip-border)",
                    boxShadow: isActive ? `0 0 0 3px color-mix(in srgb, ${s.color} 12%, transparent)` : undefined,
                  }}
                >
                  <div
                    className="w-7 h-7 rounded-lg flex items-center justify-center mb-2"
                    style={{
                      background: isZero ? "var(--muted)" : `color-mix(in srgb, ${s.color} 12%, transparent)`,
                      color: isZero ? "var(--haip-fg-subtle)" : s.color,
                    }}
                  >
                    {s.icon}
                  </div>
                  <p className="text-2xl font-extrabold leading-none tabular-nums" style={{ color: isZero ? "var(--haip-fg-subtle)" : "var(--haip-fg)" }}>
                    {n}
                  </p>
                  <p className="text-[11px] font-semibold mt-1.5" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>{s.label}</p>
                  <p className="text-[10px] mt-0.5 leading-tight" style={{ color: "var(--haip-fg-subtle)" }}>{s.blurb}</p>
                </button>
              );
            })}
          </div>

          {/* Active section list */}
          <div className="haip-card overflow-hidden">
            <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: "1px solid var(--haip-border)" }}>
              <div className="flex items-center gap-2.5">
                <div
                  className="w-6.5 h-6.5 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{ background: `color-mix(in srgb, ${section.color} 12%, transparent)`, color: section.color, width: 26, height: 26 }}
                >
                  {section.icon}
                </div>
                <div>
                  <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>{section.label}</p>
                  <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>{section.blurb}</p>
                </div>
              </div>
              {totalForSection > rows.length && (
                <span
                  className="text-[11px] font-semibold px-2 py-1 rounded-lg flex-shrink-0"
                  style={{ background: "color-mix(in srgb, var(--haip-amber, #d97706) 14%, transparent)", color: "var(--haip-amber, #d97706)" }}
                >
                  Showing {rows.length} of {totalForSection}
                </span>
              )}
            </div>

            {isCustom && from > to ? (
              <div className="py-10 text-center">
                <p className="text-sm font-medium" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>Check the dates</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>The start date is after the end date.</p>
              </div>
            ) : isLoading ? (
              <div className="p-4 space-y-2">
                {[1, 2, 3].map(i => <Skeleton key={i} className="h-16 rounded-xl" />)}
              </div>
            ) : isError ? (
              <div
                className="flex items-start gap-3 m-4 px-4 py-3.5 rounded-xl text-sm"
                style={{ background: "color-mix(in srgb, var(--haip-red, #dc2626) 8%, transparent)", border: "1px solid color-mix(in srgb, var(--haip-red, #dc2626) 30%, transparent)", color: "var(--haip-red, #dc2626)" }}
              >
                <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
                <p className="flex-1 font-medium">Couldn&apos;t load your worklist.</p>
                <button
                  onClick={() => refetch()}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors"
                  style={{ background: "var(--haip-card)", border: "1px solid color-mix(in srgb, var(--haip-red, #dc2626) 40%, transparent)", color: "var(--haip-red, #dc2626)" }}
                >
                  <RefreshCw size={12} /> Retry
                </button>
              </div>
            ) : rows.length === 0 ? (
              <div className="py-12 text-center">
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center mx-auto mb-2"
                  style={{ background: "color-mix(in srgb, var(--primary) 12%, transparent)" }}
                >
                  <UserCheck size={16} style={{ color: "var(--primary)" }} />
                </div>
                <p className="text-sm font-medium" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>Nothing here</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>{section.blurb} — all clear.</p>
              </div>
            ) : (
              <div>
                {rows.map((r, i) => (
                  <LeadRow key={r.conversation_id || r.call_id || r.task_id || i} row={r} sectionKey={active} />
                ))}
                {canLoadMore && (
                  <div className="p-3 flex justify-center" style={{ borderTop: "1px solid var(--haip-border)" }}>
                    <button
                      onClick={loadMore}
                      disabled={isLoadingMore}
                      className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-xs font-semibold transition-colors disabled:opacity-60"
                      style={{ background: "var(--haip-card)", border: "1.5px solid var(--haip-border)", color: "var(--haip-fg-2, var(--haip-fg))" }}
                    >
                      {isLoadingMore ? <RefreshCw size={12} className="animate-spin" /> : null}
                      {isLoadingMore ? "Loading…" : `Load ${Math.min(data?.section_limit ?? 50, totalForSection - rows.length)} more`}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
