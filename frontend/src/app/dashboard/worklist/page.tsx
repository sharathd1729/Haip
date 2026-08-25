"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { MessageSquare, PhoneMissed, Inbox, Clock, AlertCircle, RefreshCw, ChevronRight, Phone, Mail, AtSign } from "@/lib/icons";
import { UserCheck } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
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

const SECTIONS = [
  {
    key: "awaiting_reply",
    label: "Waiting on us",
    blurb: "They messaged last and nobody has replied",
    icon: <MessageSquare size={15} />,
    tone: "text-red-600 bg-red-50 border-red-200",
  },
  {
    key: "missed_calls",
    label: "Missed calls",
    blurb: "Came in, nobody picked up, not yet called back",
    icon: <PhoneMissed size={15} />,
    tone: "text-orange-600 bg-orange-50 border-orange-200",
  },
  {
    key: "shared_details",
    label: "Shared their details",
    blurb: "Gave us a phone number or email — high intent",
    icon: <UserCheck size={15} />,
    tone: "text-teal-700 bg-teal-50 border-teal-200",
  },
  {
    key: "new_dms",
    label: "New messages",
    blurb: "Everything that came in",
    icon: <Inbox size={15} />,
    tone: "text-blue-600 bg-blue-50 border-blue-200",
  },
  {
    key: "overdue_followups",
    label: "Overdue follow-ups",
    blurb: "Tasks past their due date",
    icon: <Clock size={15} />,
    tone: "text-amber-700 bg-amber-50 border-amber-200",
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
    return <span className="text-[11px] text-gray-400">No contact details yet</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map(i => (
        <span key={i.value} className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-gray-100 rounded text-[11px] text-gray-700 font-medium">
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
    <div className="px-4 py-3 hover:bg-gray-50/70 transition-colors border-b border-gray-50 last:border-0">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-gray-900">{lead.name}</p>
            {row.channel && (
              <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-gray-500">
                {row.channel === "instagram" ? <AtSign size={10} /> : <MessageSquare size={10} />}
                {row.channel}
              </span>
            )}
            {lead.source && (
              <span className="text-[10px] text-gray-400">via {lead.source.replace(/_/g, " ")}</span>
            )}
            {sectionKey === "awaiting_reply" && row.waiting_minutes != null && (
              <span className={cn(
                "text-[10px] font-semibold px-1.5 py-0.5 rounded",
                row.waiting_minutes > 240 ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700",
              )}>
                waiting {waitLabel(row.waiting_minutes)}
              </span>
            )}
          </div>

          {text && <p className="text-xs text-gray-600 mt-1 line-clamp-2">{text}</p>}

          {/* What the agent needs before making contact */}
          <div className="mt-1.5 space-y-1">
            <ContactChips lead={lead} />
            {!!stay.length && (
              <p className="text-[11px] text-gray-500">{stay.join(" · ")}</p>
            )}
            {lead.ai_summary && (
              <p className="text-[11px] text-gray-500 italic line-clamp-2">{lead.ai_summary}</p>
            )}
          </div>
        </div>

        <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
          <span className="text-[10px] text-gray-400 whitespace-nowrap">{whenOf(row)}</span>
          <button
            onClick={open}
            className="inline-flex items-center gap-1 px-2.5 py-1 bg-white border border-gray-200 rounded-lg text-[11px] font-semibold text-gray-700 hover:border-teal-400 hover:text-teal-700 transition-colors"
          >
            Open <ChevronRight size={11} />
          </button>
        </div>
      </div>
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

  const rows = (data?.[active as keyof Worklist] as Row[] | undefined) ?? [];
  const section = SECTIONS.find(s => s.key === active)!;

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="haip-page-title">Today</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Everyone waiting on a reply, in the order they should be dealt with.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <select
              value={range}
              onChange={e => setRange(e.target.value)}
              className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
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
                  onChange={e => setFrom(e.target.value)}
                  className="px-2 py-1.5 border border-gray-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                />
                <span className="text-gray-400 text-xs">→</span>
                <input
                  type="date"
                  value={to}
                  min={from || undefined}
                  onChange={e => setTo(e.target.value)}
                  className="px-2 py-1.5 border border-gray-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-teal-500/30"
                />
              </div>
            )}

            <button
              onClick={() => refetch()}
              title="Refresh"
              className="p-2 text-gray-400 hover:text-gray-700 transition-colors"
            >
              <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Section tabs double as the count summary */}
        <div className="flex flex-wrap gap-2 mt-4">
          {SECTIONS.map(s => {
            const n = data?.counts?.[s.key] ?? 0;
            const isActive = active === s.key;
            return (
              <button
                key={s.key}
                onClick={() => setActive(s.key)}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-xl border text-left transition-all",
                  isActive ? s.tone : "bg-white border-gray-200 text-gray-600 hover:border-gray-300",
                )}
              >
                {s.icon}
                <span className="text-xs font-semibold">{s.label}</span>
                <span className={cn(
                  "text-xs font-bold px-1.5 rounded",
                  isActive ? "bg-white/70" : "bg-gray-100 text-gray-700",
                )}>
                  {n}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl">
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-gray-800">{section.label}</p>
                <p className="text-[11px] text-gray-400">{section.blurb}</p>
              </div>
              {data?.truncated?.[active] && (
                <span className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 px-2 py-1 rounded-lg">
                  Showing first {data.section_limit} of {data.counts[active]}
                </span>
              )}
            </div>

            {isCustom && from > to ? (
              <div className="py-10 text-center">
                <p className="text-sm font-medium text-gray-600">Check the dates</p>
                <p className="text-xs text-gray-400 mt-0.5">The start date is after the end date.</p>
              </div>
            ) : isLoading ? (
              <div className="p-4 space-y-2">
                {[1, 2, 3].map(i => <Skeleton key={i} className="h-16 rounded-xl" />)}
              </div>
            ) : isError ? (
              <div className="flex items-start gap-3 m-4 px-4 py-3.5 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                <AlertCircle size={16} className="flex-shrink-0 mt-0.5" />
                <p className="flex-1 font-medium">Couldn&apos;t load your worklist.</p>
                <button
                  onClick={() => refetch()}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-red-300 text-red-700 rounded-lg text-xs font-semibold hover:bg-red-100 transition-colors"
                >
                  <RefreshCw size={12} /> Retry
                </button>
              </div>
            ) : rows.length === 0 ? (
              <div className="py-12 text-center">
                <div className="w-9 h-9 rounded-full bg-teal-50 flex items-center justify-center mx-auto mb-2">
                  <UserCheck size={16} className="text-teal-500" />
                </div>
                <p className="text-sm font-medium text-gray-600">Nothing here</p>
                <p className="text-xs text-gray-400 mt-0.5">{section.blurb} — all clear.</p>
              </div>
            ) : (
              <div>
                {rows.map((r, i) => (
                  <LeadRow key={r.conversation_id || r.call_id || r.task_id || i} row={r} sectionKey={active} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
