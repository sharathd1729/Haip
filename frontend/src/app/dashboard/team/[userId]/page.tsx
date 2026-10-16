"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { ShieldAlert, Phone, MessageSquare, LayoutGrid, ArrowLeft } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { DateRangeFilterBar, DateRangeValue } from "@/components/dashboard/DateRangeFilterBar";

// Agent Profile page -- everything one sales agent handled (leads, calls
// with recording+AI analysis, WhatsApp/IG messages), attributed to them.
// Owner/manager can view any agent's profile; an agent can only view their
// own -- same binary check the backend (users.py's _require_self_or_owner)
// already enforces, mirrored here so a blocked view doesn't even attempt
// the queries. Reuses existing surfaces rather than re-rendering them:
// Calls rows link into /dashboard/calls/[id] (recording+AI analysis
// already render there); Messages rows link into /dashboard/inbox (thread
// view already renders there).

interface Scorecard {
  agent_id: string; agent_name: string; leads_handled: number;
  avg_response_seconds: number; response_count: number;
  followups_total: number; followups_completed: number; followups_overdue: number;
  calls_answered: number; calls_missed: number; calls_missed_recovered: number;
  ai_drafts_total: number; ai_drafts_approved: number; ai_drafts_rejected: number;
  conversions: number;
}
interface CallRow {
  id: string; started_at: string; direction: "inbound" | "outbound";
  guest_name?: string; guest_phone: string; disposition?: string;
}
interface MessageRow {
  conversation_id: string; channel: string; guest_name: string | null;
  message_count: number; last_message_at: string | null;
}

function formatSeconds(s: number): string {
  if (!s) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  const m = Math.floor(s / 60);
  return `${m}m`;
}

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="p-3 rounded-xl border flex-1 min-w-[120px]" style={{ borderColor: "var(--haip-border)", background: "var(--haip-card)" }}>
      <div className="text-[10px] font-medium uppercase tracking-wide" style={{ color: "var(--haip-fg-subtle)" }}>{label}</div>
      <div className="text-lg font-bold mt-1" style={{ color: "var(--haip-fg)" }}>{value}</div>
    </div>
  );
}

type Tab = "overview" | "calls" | "messages";

export default function AgentProfilePage() {
  const { userId } = useParams<{ userId: string }>();
  const { data: session } = useSession();
  const role = session?.user?.role;
  const isOwnerView = role === "owner" || role === "manager";
  const isSelf = session?.user?.id === userId;

  const [tab, setTab] = useState<Tab>("overview");
  const [range, setRange] = useState<DateRangeValue>({ preset: "today" });

  const dateParams: Record<string, string> = { date_preset: range.preset };
  if (range.preset === "custom") {
    if (range.date_from) dateParams.date_from = range.date_from;
    if (range.date_to) dateParams.date_to = range.date_to;
  }

  const allowed = isSelf || isOwnerView;

  const { data: scorecard, isLoading: scorecardLoading } = useQuery<Scorecard>({
    queryKey: ["agent-scorecard", userId, dateParams],
    queryFn: () => api.get(`/users/${userId}/scorecard`, { params: dateParams }).then(r => r.data),
    enabled: allowed,
  });

  const { data: calls, isLoading: callsLoading } = useQuery<CallRow[]>({
    queryKey: ["agent-calls", userId, dateParams],
    queryFn: () => api.get("/calls", { params: { ...dateParams, agent_id: userId } }).then(r => r.data.items ?? []),
    enabled: allowed && tab === "calls",
  });

  const { data: messages, isLoading: messagesLoading } = useQuery<MessageRow[]>({
    queryKey: ["agent-messages", userId, dateParams],
    queryFn: () => api.get(`/users/${userId}/messages`, { params: dateParams }).then(r => r.data),
    enabled: allowed && tab === "messages",
  });

  if (!allowed) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-center px-6 bg-[#F8FAFC]">
        <ShieldAlert size={32} className="text-gray-300" />
        <p className="text-sm font-semibold text-gray-600">You can only view your own profile</p>
        <Link href="/dashboard" className="text-xs text-teal-600 hover:underline">Back to dashboard</Link>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      <div className="px-6 py-5 bg-white border-b border-gray-100 flex-shrink-0 space-y-3">
        <div className="flex items-center gap-2">
          {isOwnerView && !isSelf && (
            <Link href="/dashboard/settings/team" className="text-gray-400 hover:text-gray-600">
              <ArrowLeft size={16} />
            </Link>
          )}
          <div>
            <h1 className="haip-page-title haip-page-title--keep">{scorecardLoading ? "Loading…" : scorecard?.agent_name || "Agent"}</h1>
            <p className="text-sm text-gray-400 mt-0.5">{isSelf ? "Your calls, messages and leads" : "Calls, messages and leads handled"}</p>
          </div>
        </div>
        <DateRangeFilterBar value={range} onChange={setRange} />
        <div className="flex gap-1">
          {([
            ["overview", "Overview", LayoutGrid],
            ["calls", "Calls", Phone],
            ["messages", "Messages", MessageSquare],
          ] as const).map(([key, label, Icon]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
                tab === key
                  ? "bg-teal-50 border-teal-300 text-teal-800"
                  : "bg-white border-gray-200 text-gray-600 hover:border-gray-300",
              )}
            >
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 p-6">
        {tab === "overview" && (
          scorecardLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : scorecard ? (
            <div className="flex flex-wrap gap-3">
              <StatTile label="Leads handled" value={scorecard.leads_handled} />
              <StatTile label="Avg response" value={formatSeconds(scorecard.avg_response_seconds)} />
              <StatTile label="Calls answered" value={`${scorecard.calls_answered}/${scorecard.calls_answered + scorecard.calls_missed}`} />
              <StatTile label="Conversions" value={scorecard.conversions} />
              <StatTile label="Follow-ups" value={`${scorecard.followups_completed}/${scorecard.followups_total}`} />
              <StatTile label="AI drafts approved" value={`${scorecard.ai_drafts_approved}/${scorecard.ai_drafts_total}`} />
            </div>
          ) : null
        )}

        {tab === "calls" && (
          <div className="space-y-2">
            {callsLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : !calls?.length ? (
              <p className="text-sm text-gray-400">No calls in this period.</p>
            ) : calls.map(c => (
              <Link
                key={c.id}
                href={`/dashboard/calls/${c.id}`}
                className="block p-3 rounded-xl border border-gray-200 hover:border-teal-300 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-gray-800">{c.guest_name || c.guest_phone}</span>
                  {c.disposition && (
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-teal-700 bg-teal-50 px-1.5 py-0.5 rounded">{c.disposition}</span>
                  )}
                </div>
                <div className="text-xs text-gray-400 mt-1">{c.direction} · {new Date(c.started_at).toLocaleString()}</div>
              </Link>
            ))}
          </div>
        )}

        {tab === "messages" && (
          <div className="space-y-2">
            {messagesLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : !messages?.length ? (
              <p className="text-sm text-gray-400">No conversations replied to in this period.</p>
            ) : messages.map(m => (
              <Link
                key={m.conversation_id}
                href={`/dashboard/inbox?conversation=${m.conversation_id}`}
                className="block p-3 rounded-xl border border-gray-200 hover:border-teal-300 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-gray-800">{m.guest_name || "Guest"}</span>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 bg-gray-50 px-1.5 py-0.5 rounded">{m.channel}</span>
                </div>
                <div className="text-xs text-gray-400 mt-1">
                  {m.message_count} repl{m.message_count === 1 ? "y" : "ies"}
                  {m.last_message_at ? ` · last ${new Date(m.last_message_at).toLocaleString()}` : ""}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
