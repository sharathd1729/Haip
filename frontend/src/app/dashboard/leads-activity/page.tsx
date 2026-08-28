"use client";
import { useState, useMemo, Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { MessageSquare, AtSign, Phone, Sparkles } from "@/lib/icons";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

/** Detailed per-lead report -- in-app page. Same lead_activity_service
 * query the daily agent/owner email reports use; this is the "View all
 * N leads" destination the owner email's condensed rows link into. */

interface Lead {
  inquiry_id: string;
  guest_name: string;
  channel: string;
  snippet: string;
  when: string | null;
  status: "booked" | "quoted" | "progress" | "lost" | string;
  intent: string | null;
  route_mentioned: string | null;
  guest_count: string | null;
  quoted_amount: number | null;
  special_requests: string | null;
  upsell_offered: string | null;
  upsell_accepted: boolean | null;
  lead_quality: { label: string } | null;
  ai_lead_analysis: string | null;
  agent_id?: string;
  agent_name?: string;
}
interface LeadsActivityResponse {
  date: string;
  agent_id: string | null;
  leads: Lead[];
}

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  booked: { label: "Booked", color: "var(--haip-green, #10B981)" },
  quoted: { label: "Quoted", color: "var(--haip-blue, #2563EB)" },
  progress: { label: "Awaiting reply", color: "var(--haip-amber, #F59E0B)" },
  lost: { label: "Lost", color: "var(--haip-red, #EF4444)" },
};

const CHANNEL_FILTERS = [
  { key: "all", label: "All channels" },
  { key: "call", label: "Calls" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "instagram", label: "Instagram" },
];

function ChannelIcon({ channel }: { channel: string }) {
  if (channel === "instagram") return <AtSign size={13} style={{ color: "var(--haip-fg-subtle)" }} />;
  if (channel === "call") return <Phone size={13} style={{ color: "var(--primary)" }} />;
  return <MessageSquare size={13} style={{ color: "#25D366" }} />;
}

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLE[status] ?? { label: status, color: "var(--haip-fg-subtle)" };
  return (
    <span
      className="text-[10.5px] font-bold uppercase tracking-wide px-2.5 py-1 rounded-full flex-shrink-0"
      style={{ color: s.color, background: `color-mix(in srgb, ${s.color} 14%, transparent)` }}
    >
      {s.label}
    </span>
  );
}

function fmtWhen(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function fmtAmount(v: number) {
  return `₹${v.toLocaleString("en-IN")}`;
}

function LeadCard({ lead }: { lead: Lead }) {
  const fields = [
    { label: "Route", value: lead.route_mentioned },
    { label: "Guests", value: lead.guest_count },
    { label: "Price quoted", value: lead.quoted_amount != null ? fmtAmount(lead.quoted_amount) : "Not yet quoted" },
    { label: "Lead quality", value: lead.lead_quality?.label ?? null },
  ].filter(f => f.value);

  return (
    <div className="haip-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="w-6.5 h-6.5 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: "var(--muted)", width: 26, height: 26 }}
          >
            <ChannelIcon channel={lead.channel} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate" style={{ color: "var(--haip-fg)" }}>{lead.guest_name}</p>
            <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>
              {lead.channel} · {fmtWhen(lead.when)}
            </p>
          </div>
        </div>
        <StatusBadge status={lead.status} />
      </div>

      {lead.intent && (
        <p className="text-xs mt-2.5 p-2.5 rounded-lg" style={{ color: "var(--haip-fg-2, var(--haip-fg))", background: "var(--muted)" }}>
          {lead.intent}
        </p>
      )}

      {!!fields.length && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3 pt-3" style={{ borderTop: "1px solid var(--haip-border)" }}>
          {fields.map(f => (
            <div key={f.label}>
              <p className="text-[9.5px] font-bold uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>{f.label}</p>
              <p className="text-xs mt-0.5 font-medium" style={{ color: "var(--haip-fg)" }}>{f.value}</p>
            </div>
          ))}
        </div>
      )}

      {lead.upsell_offered && (
        <div
          className="flex items-start gap-2 mt-2.5 p-2.5 rounded-lg text-xs"
          style={{
            background: lead.upsell_accepted
              ? "color-mix(in srgb, var(--haip-green, #10B981) 12%, transparent)"
              : "color-mix(in srgb, var(--haip-amber, #F59E0B) 12%, transparent)",
            color: "var(--haip-fg-2, var(--haip-fg))",
          }}
        >
          <span
            className="w-4.5 h-4.5 rounded-full flex items-center justify-center flex-shrink-0 text-white text-[10px] font-bold"
            style={{ width: 18, height: 18, background: lead.upsell_accepted ? "var(--haip-green, #10B981)" : "var(--haip-amber, #F59E0B)" }}
          >
            {lead.upsell_accepted ? "✓" : "?"}
          </span>
          <span>
            <b>Upsell {lead.upsell_accepted ? "accepted" : lead.upsell_accepted === false ? "declined" : "offered"}</b> — {lead.upsell_offered}
          </span>
        </div>
      )}

      {lead.ai_lead_analysis && (
        <div
          className="flex items-start gap-2 mt-2.5 p-2.5 rounded-lg text-xs"
          style={{ background: "color-mix(in srgb, #5B5BCE 10%, transparent)", borderLeft: "3px solid #5B5BCE" }}
        >
          <Sparkles size={13} style={{ color: "#5B5BCE", flexShrink: 0, marginTop: 1 }} />
          <div>
            <p className="text-[9.5px] font-bold uppercase tracking-wide" style={{ color: "#6A6AD6" }}>AI analysis</p>
            <p className="mt-0.5" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>{lead.ai_lead_analysis}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function todayISO() {
  return new Date().toISOString().split("T")[0];
}

function LeadsActivityInner() {
  const params = useSearchParams();
  const router = useRouter();
  const [date, setDate] = useState(params.get("date") || todayISO());
  const agentId = params.get("agent_id");
  const [channelFilter, setChannelFilter] = useState("all");

  const { data, isLoading, isError } = useQuery<LeadsActivityResponse>({
    queryKey: ["leads-activity", date, agentId],
    queryFn: () =>
      api
        .get("/leads-activity", { params: { date, ...(agentId ? { agent_id: agentId } : {}) } })
        .then(r => r.data),
    staleTime: 60_000,
  });

  const leads = useMemo(() => {
    const all = data?.leads ?? [];
    return channelFilter === "all" ? all : all.filter(l => l.channel === channelFilter);
  }, [data, channelFilter]);

  const grouped = useMemo(() => {
    const byAgent = new Map<string, { name: string; leads: Lead[] }>();
    for (const lead of leads) {
      const key = lead.agent_id || "unknown";
      if (!byAgent.has(key)) byAgent.set(key, { name: lead.agent_name || "Unassigned", leads: [] });
      byAgent.get(key)!.leads.push(lead);
    }
    return Array.from(byAgent.values());
  }, [leads]);

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      <div className="px-6 py-5 flex-shrink-0" style={{ background: "var(--haip-card)", borderBottom: "1px solid var(--haip-border)" }}>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="haip-page-title">Lead Activity</h1>
            <p className="text-sm mt-0.5" style={{ color: "var(--haip-fg-subtle)" }}>
              Every lead a human agent handled{agentId ? "" : ", every agent"} — {date}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {agentId && (
              <button
                onClick={() => router.push("/dashboard/leads-activity" + (date ? `?date=${date}` : ""))}
                className="text-[11px] font-semibold px-3 py-1.5 rounded-lg"
                style={{ border: "1px solid var(--haip-border)", color: "var(--haip-fg-subtle)" }}
              >
                Clear agent filter
              </button>
            )}
            <input
              type="date"
              value={date}
              onChange={e => setDate(e.target.value)}
              className="text-xs rounded-lg px-2.5 py-1.5"
              style={{ background: "var(--haip-card)", border: "1px solid var(--haip-border)", color: "var(--haip-fg)" }}
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-2 mt-4">
          {CHANNEL_FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => setChannelFilter(f.key)}
              className="text-[11.5px] font-semibold px-3 py-1.5 rounded-full transition-colors"
              style={
                channelFilter === f.key
                  ? { border: "1.5px solid var(--primary)", color: "var(--primary)", background: "color-mix(in srgb, var(--primary) 10%, transparent)" }
                  : { border: "1.5px solid var(--haip-border)", color: "var(--haip-fg-2, var(--haip-fg))", background: "var(--haip-card)" }
              }
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 p-6">
        {isLoading ? (
          <div className="space-y-3 max-w-3xl mx-auto">
            {[1, 2, 3].map(i => <Skeleton key={i} className="h-32 rounded-xl" />)}
          </div>
        ) : isError ? (
          <p className="text-sm text-center py-10" style={{ color: "var(--haip-fg-subtle)" }}>Couldn&apos;t load lead activity.</p>
        ) : grouped.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-sm font-medium" style={{ color: "var(--haip-fg-2, var(--haip-fg))" }}>Nothing here</p>
            <p className="text-xs mt-1" style={{ color: "var(--haip-fg-subtle)" }}>No human-handled leads for this day{agentId ? " and agent" : ""}.</p>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {grouped.map(group => (
              <div key={group.name}>
                {!agentId && (
                  <div className="flex items-center gap-2.5 mb-3">
                    <div
                      className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white"
                      style={{ background: "var(--primary)" }}
                    >
                      {group.name[0]?.toUpperCase()}
                    </div>
                    <div>
                      <p className="text-sm font-semibold" style={{ color: "var(--haip-fg)" }}>{group.name}</p>
                      <p className="text-[11px]" style={{ color: "var(--haip-fg-subtle)" }}>{group.leads.length} lead{group.leads.length !== 1 ? "s" : ""}</p>
                    </div>
                  </div>
                )}
                <div className="space-y-3">
                  {group.leads.map(lead => <LeadCard key={lead.inquiry_id} lead={lead} />)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function LeadsActivityPage() {
  return (
    <Suspense fallback={null}>
      <LeadsActivityInner />
    </Suspense>
  );
}
