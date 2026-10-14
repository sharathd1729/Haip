"use client";
// "Needs action" -- the default Leads view. Groups open leads by the next
// thing an agent should do (GET /leads/needs-action decides the grouping;
// each lead appears in exactly one group). Desktop shows a detail panel for
// the selected lead; on mobile a row opens the full lead page.
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Sparkles, Clock, PhoneCall, Flag, Users, ArrowRight, Loader2, Send, CheckCircle2,
} from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { ChannelIcon } from "@/components/inbox/ChannelIcon";
import { usePipelineStages } from "@/hooks/usePipelineStages";
import { formatDuration, useApproveAndSendDraft, type LeadCard } from "@/components/leads/LeadCard";
import type { LeadsFilters } from "@/components/leads/LeadsFilterBar";

type BucketKey = "draft_ready" | "waiting" | "call" | "followup";

interface NeedsActionResponse {
  window_days: number;
  kpis: {
    waiting: number;
    waiting_oldest_seconds: number | null;
    drafts_ready: number;
    phone_not_called: number;
    unassigned_recent: number;
    sold_this_month: number;
  };
  buckets: { key: BucketKey; total: number; leads: LeadCard[] }[];
}

// Tone classes carry the meaning (amber = someone is waiting on us, teal =
// the AI already did the work, green = warm lead, violet = needs a person).
const BUCKETS: Record<BucketKey, {
  title: string; hint: string; action: string; icon: typeof Clock;
  bar: string; chip: string; text: string;
}> = {
  draft_ready: {
    title: "AI reply ready to send", hint: "The guest is waiting and a reply is already drafted — check it and send",
    action: "Send reply", icon: Sparkles, bar: "bg-teal-600", chip: "bg-teal-50 text-teal-700", text: "text-teal-700",
  },
  waiting: {
    title: "Waiting for our reply", hint: "The guest messaged last and hasn't heard back",
    action: "Reply", icon: Clock, bar: "bg-amber-500", chip: "bg-amber-50 text-amber-700", text: "text-amber-700",
  },
  call: {
    title: "Shared a number — call them", hint: "They gave a phone number and nobody has spoken to them yet",
    action: "Call", icon: PhoneCall, bar: "bg-emerald-600", chip: "bg-emerald-50 text-emerald-700", text: "text-emerald-700",
  },
  followup: {
    title: "Flagged for the team", hint: "The AI answered but says a person should follow up",
    action: "Open", icon: Flag, bar: "bg-violet-500", chip: "bg-violet-50 text-violet-700", text: "text-violet-700",
  },
};

function statusLabel(key: BucketKey, lead: LeadCard): string {
  if (key === "waiting" || key === "draft_ready") {
    const s = lead.response_time_seconds;
    return s != null ? `Waiting ${formatDuration(s)}` : "Waiting";
  }
  if (key === "call") return "Not called";
  return "Needs a person";
}

function intentOf(lead: LeadCard): string {
  const intent = lead.ai_analysis?.intent;
  if (intent && intent !== "unknown") return intent.charAt(0).toUpperCase() + intent.slice(1);
  const firstSentence = lead.ai_summary?.split(/(?<=\.)\s/)[0];
  return firstSentence || "No details yet";
}

function guestsLabel(lead: LeadCard): string | null {
  if (!lead.adults && !lead.children) return null;
  const parts = [];
  if (lead.adults) parts.push(`${lead.adults} adult${lead.adults === 1 ? "" : "s"}`);
  if (lead.children) parts.push(`${lead.children} kid${lead.children === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

function datesLabel(lead: LeadCard): string | null {
  const fmt = (d?: string | null) =>
    d ? new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : null;
  const a = fmt(lead.check_in), b = fmt(lead.check_out);
  if (!a && !b) return null;
  return a && b ? `${a} – ${b}` : (a || b);
}

// ─── Summary tiles ────────────────────────────────────────────────────────────

// IST calendar date, `daysAgo` days back -- the leads list filters by IST day.
function istDate(daysAgo = 0): string {
  const d = new Date(Date.now() + 5.5 * 3600_000 - daysAgo * 86_400_000);
  return d.toISOString().slice(0, 10);
}

function Kpis({
  data, focus, onFocus, onOpenPipeline,
}: {
  data: NeedsActionResponse; focus: BucketKey | null;
  onFocus: (b: BucketKey | null) => void; onOpenPipeline?: (f: LeadsFilters) => void;
}) {
  const k = data.kpis;
  // The first three narrow this list to one group (click again to show all);
  // the last two open the Pipeline board with the matching filter.
  const tiles: { label: string; value: number; note: string; tone: string; dot: string; bucket?: BucketKey; filters?: LeadsFilters }[] = [
    { label: "Waiting on us", value: k.waiting, note: k.waiting_oldest_seconds ? `oldest ${formatDuration(k.waiting_oldest_seconds)}` : "all caught up", tone: "text-amber-700", dot: "bg-amber-500", bucket: "waiting" },
    { label: "AI replies to send", value: k.drafts_ready, note: "ready now", tone: "text-teal-700", dot: "bg-teal-600", bucket: "draft_ready" },
    { label: "Shared a phone", value: k.phone_not_called, note: "not called yet", tone: "text-emerald-700", dot: "bg-emerald-600", bucket: "call" },
    { label: "Unassigned", value: k.unassigned_recent, note: "last 3 days", tone: "text-gray-700", dot: "bg-gray-400", filters: { assigned_to: "unassigned", date_from: istDate(2) } },
    { label: "Sold this month", value: k.sold_this_month, note: "closed won", tone: "text-violet-700", dot: "bg-violet-500", filters: { booked_date_from: `${istDate().slice(0, 8)}01` } },
  ];
  return (
    <div className="flex gap-2.5 overflow-x-auto haip-scrollbar-x pb-1 lg:grid lg:grid-cols-5 lg:overflow-visible">
      {tiles.map(t => {
        const on = !!t.bucket && focus === t.bucket;
        const click = () => {
          if (t.bucket) onFocus(on ? null : t.bucket);
          else if (t.filters) onOpenPipeline?.(t.filters);
        };
        return (
        <button key={t.label} type="button" onClick={click} aria-pressed={t.bucket ? on : undefined}
          title={t.bucket ? (on ? "Show all groups" : `Show only “${t.label}”`) : "Open in Pipeline"}
          className={cn("haip-card flex-shrink-0 min-w-[150px] px-4 py-3 text-left cursor-pointer transition-shadow hover:shadow-md outline-none focus-visible:ring-2 focus-visible:ring-teal-600",
            on && "ring-2 ring-teal-600")}>
          <span className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--haip-fg-subtle)" }}>
            <span className={cn("w-2 h-2 rounded-full", t.dot)} />
            {t.label}
          </span>
          <span className="mt-1 flex items-baseline gap-2">
            <span className={cn("text-2xl font-bold tabular-nums", t.tone)} style={{ fontFamily: "var(--font-display)" }}>{t.value}</span>
            <span className="text-xs" style={{ color: "var(--haip-fg-muted)" }}>{t.note}</span>
          </span>
        </button>
        );
      })}
    </div>
  );
}

// ─── Calling a lead ───────────────────────────────────────────────────────────

// The "Call" button places the call: the IVR rings the agent's own phone, then
// bridges to the guest -- the same POST /calls/click-to-call the Calls page
// uses, naming the lead so the number never has to reach this list. It used to
// just open the lead page, so tapping "Call" dialled nobody. Any failure
// (no agent phone on file, IVR not set up, guest has no number) is shown as
// the server's own reason.
function useCallLead(lead: LeadCard) {
  const { toast } = useToast();
  return useMutation({
    mutationFn: () => api.post("/calls/click-to-call", { inquiry_id: lead.inquiry_id }),
    onSuccess: () => toast({
      variant: "success", title: "Calling…",
      description: `Your phone will ring first, then we'll connect you to ${lead.display_name}.`,
    }),
    onError: (err: any) => {
      const raw = err?.response?.data?.detail;
      const description = typeof raw === "string"
        ? raw
        : Array.isArray(raw) ? raw.map((e: any) => e?.msg ?? JSON.stringify(e)).join("; ") : "Could not start the call.";
      toast({ variant: "error", title: "Call failed", description });
    },
  });
}

// ─── One lead row ─────────────────────────────────────────────────────────────

function ActionRow({
  lead, bucket, selected, onSelect, stageLabel,
}: {
  lead: LeadCard; bucket: BucketKey; selected: boolean; onSelect: () => void; stageLabel: string | null;
}) {
  const router = useRouter();
  const meta = BUCKETS[bucket];
  const send = useApproveAndSendDraft(lead.inquiry_id);
  const callLead = useCallLead(lead);
  const hasPhone = lead.identity_signals?.includes("phone");
  const chips = [guestsLabel(lead), datesLabel(lead), hasPhone && bucket !== "call" ? "Phone shared" : null].filter(Boolean) as string[];
  const busy = send.isPending || callLead.isPending;

  const act = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (bucket === "draft_ready" && lead.pending_draft) {
      send.mutate({ conversationId: lead.pending_draft.conversation_id, messageId: lead.pending_draft.message_id });
    } else if (bucket === "call" && hasPhone) {
      callLead.mutate();
    } else {
      router.push(`/dashboard/leads/${lead.inquiry_id}`);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={e => { if (e.key === "Enter") onSelect(); }}
      className={cn(
        "haip-card px-4 py-3 flex items-center gap-3 cursor-pointer transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-teal-600",
        selected && "ring-2 ring-teal-600",
      )}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-semibold text-sm truncate" style={{ color: "var(--haip-fg)" }}>{lead.display_name}</span>
          <ChannelIcon channel={lead.source ?? lead.primary_channel ?? ""} showLabel className="flex-shrink-0" />
          {stageLabel && (
            <span className="hidden sm:inline text-[11px] truncate" style={{ color: "var(--haip-fg-muted)" }}>· {stageLabel}</span>
          )}
        </div>
        <p className="text-[13px] mt-0.5 truncate" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>{intentOf(lead)}</p>
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {chips.map(c => (
              <span key={c} className={cn("text-[11px] font-medium px-2 py-0.5 rounded-full",
                c === "Phone shared" ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-600")}>{c}</span>
            ))}
          </div>
        )}
      </div>
      <div className="flex flex-col sm:flex-row items-end sm:items-center gap-2 flex-shrink-0">
        <span className={cn("text-[11px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap", meta.chip)}>
          {statusLabel(bucket, lead)}
        </span>
        <button
          type="button"
          onClick={act}
          disabled={busy}
          className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-60 whitespace-nowrap"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : null}
          {callLead.isPending ? "Calling…" : meta.action}
        </button>
      </div>
    </div>
  );
}

// ─── Detail panel (desktop) ───────────────────────────────────────────────────

function DetailPanel({ lead, bucket, stageLabel }: { lead: LeadCard; bucket: BucketKey; stageLabel: string | null }) {
  const router = useRouter();
  const send = useApproveAndSendDraft(lead.inquiry_id);
  const callLead = useCallLead(lead);
  const facts: [string, string][] = [
    ["Guests", guestsLabel(lead) ?? "Not shared yet"],
    ["Dates", datesLabel(lead) ?? "Not shared yet"],
    ["Budget", lead.budget_range_label ?? (lead.budget_estimate ? `₹${Number(lead.budget_estimate).toLocaleString("en-IN")}` : "—")],
    ["Stage", stageLabel ?? "—"],
  ];

  return (
    <aside className="haip-card p-5 flex flex-col gap-4 sticky top-0">
      <div>
        <h2 className="text-lg font-bold" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display)" }}>{lead.display_name}</h2>
        <div className="flex items-center gap-2 mt-1">
          <ChannelIcon channel={lead.source ?? lead.primary_channel ?? ""} showLabel />
          {lead.identity_signals?.includes("phone") && (
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700">Phone shared</span>
          )}
          <span className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>
            {lead.assigned_agent_name ? `· ${lead.assigned_agent_name}` : "· Unassigned"}
          </span>
        </div>
      </div>

      <div className="rounded-xl bg-teal-50 p-4">
        <p className="text-[10px] font-bold uppercase tracking-wider text-teal-800">What they want</p>
        <p className="text-sm mt-1.5 leading-relaxed text-gray-800">{lead.ai_summary || intentOf(lead)}</p>
      </div>

      <dl className="grid grid-cols-2 gap-2">
        {facts.map(([k, v]) => (
          <div key={k} className="rounded-lg border px-3 py-2" style={{ borderColor: "var(--haip-border)" }}>
            <dt className="text-[11px]" style={{ color: "var(--haip-fg-muted)" }}>{k}</dt>
            <dd className={cn("text-sm font-semibold mt-0.5", v === "Not shared yet" ? "text-amber-700" : "")} style={v === "Not shared yet" ? undefined : { color: "var(--haip-fg)" }}>{v}</dd>
          </div>
        ))}
      </dl>

      {bucket === "followup" && lead.needs_agent_followup_reason && (
        <div className="rounded-xl bg-violet-50 p-3 text-sm text-violet-900">
          <span className="font-semibold">Why a person: </span>{lead.needs_agent_followup_reason}
        </div>
      )}

      {lead.pending_draft && bucket === "draft_ready" && (
        <div>
          <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--haip-fg-subtle)" }}>AI reply ready</p>
          <p className="mt-1.5 rounded-xl border border-teal-200 bg-white p-3 text-sm leading-relaxed text-gray-700">
            {lead.pending_draft.preview}{lead.pending_draft.preview.length >= 140 ? "…" : ""}
          </p>
          <button
            type="button"
            onClick={() => send.mutate({ conversationId: lead.pending_draft!.conversation_id, messageId: lead.pending_draft!.message_id })}
            disabled={send.isPending}
            className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-lg bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-60"
          >
            {send.isPending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            Send reply
          </button>
        </div>
      )}

      {bucket === "call" && lead.identity_signals?.includes("phone") && (
        <button
          type="button"
          onClick={() => callLead.mutate()}
          disabled={callLead.isPending}
          className="inline-flex items-center justify-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-lg bg-teal-700 text-white hover:bg-teal-800 disabled:opacity-60"
        >
          {callLead.isPending ? <Loader2 size={14} className="animate-spin" /> : <PhoneCall size={14} />}
          {callLead.isPending ? "Calling…" : "Call now"}
        </button>
      )}

      <button
        type="button"
        onClick={() => router.push(`/dashboard/leads/${lead.inquiry_id}`)}
        className="inline-flex items-center justify-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-lg border hover:bg-gray-50"
        style={{ borderColor: "var(--haip-border)", color: "var(--haip-fg)" }}
      >
        Open full lead — chat, calls, timeline <ArrowRight size={14} />
      </button>
    </aside>
  );
}

// ─── View ─────────────────────────────────────────────────────────────────────

export function NeedsActionView({ onOpenPipeline }: { onOpenPipeline?: (f: LeadsFilters) => void } = {}) {
  const router = useRouter();
  const { data: stages = [] } = usePipelineStages();
  const stageLabels = useMemo(() => Object.fromEntries(stages.map(s => [s.key, s.label])), [stages]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<BucketKey | null>(null);

  const { data, isLoading, isError, refetch } = useQuery<NeedsActionResponse>({
    // Under ["leads", ...] so the page's refresh button and the send-draft
    // hook's invalidation refresh this view too.
    queryKey: ["leads", "needs-action"],
    queryFn: () => api.get("/leads/needs-action").then(r => r.data),
    staleTime: 10_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,       // see the pipeline query: pick-up on another device must show the latest
    refetchOnReconnect: true,
  });

  const flat = useMemo(
    () => (data?.buckets ?? []).filter(b => !focus || b.key === focus).flatMap(b => b.leads.map(l => ({ lead: l, bucket: b.key }))),
    [data, focus],
  );
  const selected = flat.find(f => f.lead.inquiry_id === selectedId) ?? flat[0];

  // Keep a valid selection when the list refreshes and the old one is gone.
  useEffect(() => {
    if (selectedId && !flat.some(f => f.lead.inquiry_id === selectedId)) setSelectedId(null);
  }, [flat, selectedId]);

  const onSelect = (id: string) => {
    // Phones and tablets have no side panel -- go straight to the lead.
    if (typeof window !== "undefined" && window.matchMedia("(max-width: 1023px)").matches) {
      router.push(`/dashboard/leads/${id}`);
    } else {
      setSelectedId(id);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ color: "var(--haip-fg-muted)" }}>
        <Loader2 size={18} className="animate-spin" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 text-sm" style={{ color: "var(--haip-fg-subtle)" }}>
        Couldn&apos;t load leads that need action.
        <button onClick={() => refetch()} className="font-semibold text-teal-700 underline">Try again</button>
      </div>
    );
  }

  const nonEmpty = data.buckets.filter(b => b.total > 0 && (!focus || b.key === focus));

  return (
    <div className="flex-1 overflow-y-auto haip-scrollbar px-3 sm:px-5 py-4 space-y-5">
      <Kpis data={data} focus={focus} onFocus={setFocus} onOpenPipeline={onOpenPipeline} />

      {nonEmpty.length === 0 ? (
        <div className="haip-card py-14 flex flex-col items-center gap-2 text-center">
          <CheckCircle2 size={28} className="text-emerald-600" />
          <p className="font-semibold" style={{ color: "var(--haip-fg)" }}>All caught up</p>
          <p className="text-sm" style={{ color: "var(--haip-fg-subtle)" }}>
            No one is waiting, no drafts to send and every shared number has been called.
          </p>
        </div>
      ) : (
        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-5 lg:items-start">
          <div className="space-y-6">
            {nonEmpty.map(b => {
              const meta = BUCKETS[b.key];
              const Icon = meta.icon;
              return (
                <section key={b.key} aria-labelledby={`na-${b.key}`}>
                  <div className="flex items-start gap-2.5 mb-2.5">
                    <span className={cn("w-1 self-stretch rounded-full", meta.bar)} />
                    <div>
                      <h2 id={`na-${b.key}`} className="flex items-center gap-2 text-[15px] font-bold" style={{ color: "var(--haip-fg)", fontFamily: "var(--font-display)" }}>
                        <Icon size={15} className={meta.text} />
                        {meta.title}
                        <span className={cn("text-sm tabular-nums", meta.text)}>{b.total}</span>
                      </h2>
                      <p className="text-xs" style={{ color: "var(--haip-fg-subtle)" }}>{meta.hint}</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    {b.leads.map(l => (
                      <ActionRow
                        key={l.inquiry_id}
                        lead={l}
                        bucket={b.key}
                        selected={selected?.lead.inquiry_id === l.inquiry_id}
                        onSelect={() => onSelect(l.inquiry_id)}
                        stageLabel={l.stage_key ? stageLabels[l.stage_key] ?? null : null}
                      />
                    ))}
                    {b.total > b.leads.length && (
                      <p className="text-xs pl-1" style={{ color: "var(--haip-fg-muted)" }}>
                        + {b.total - b.leads.length} more — use the Pipeline view to see them all
                      </p>
                    )}
                  </div>
                </section>
              );
            })}
            <p className="flex items-center gap-1.5 text-xs pb-2" style={{ color: "var(--haip-fg-muted)" }}>
              <Users size={12} /> Open leads active in the last {data.window_days} days. Refreshes every minute.
            </p>
          </div>

          {selected && (
            <div className="hidden lg:block">
              <DetailPanel
                lead={selected.lead}
                bucket={selected.bucket}
                stageLabel={selected.lead.stage_key ? stageLabels[selected.lead.stage_key] ?? null : null}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
