"use client";
// WhatsApp inbox analytics (WhatsApp step 4): first-response time, conversations per team member and message cost.
// Backend: GET /messaging/inbox-analytics (owner/manager), services/wa_inbox_analytics.py.
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

interface InboxAnalyticsData {
  period: { days: number };
  first_response: { turns: number; answered_pct: number | null; median_seconds: number | null; p90_seconds: number | null; within_pct: Record<string, number | null> };
  people: { user_id: string; name: string; conversations: number; messages: number }[];
  cost: { messages: number; amount_inr: number; by_category: Record<string, { messages: number; amount_inr: number }> };
}

const PERIODS = [7, 14, 30, 90];

function duration(s: number | null): string {
  if (s === null) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}
const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

export function InboxAnalytics({ days }: { days: number }) {
  const period = PERIODS.includes(days) ? days : 30;
  const { data, isLoading, isError, refetch } = useQuery<InboxAnalyticsData>({
    queryKey: ["wa-inbox-analytics", period],
    queryFn: () => api.get("/messaging/inbox-analytics", { params: { days: period } }).then(r => r.data),
    staleTime: 60_000,
  });
  if (isLoading) return <Skeleton className="h-40 rounded-2xl" />;
  if (isError || !data) {
    return (
      <div className="haip-card p-5 text-center">
        <p className="text-sm text-[var(--haip-fg-2)]">Couldn&apos;t load inbox analytics.</p>
        <button type="button" onClick={() => refetch()} className="mt-2 min-h-11 px-3 text-xs font-semibold text-primary">Try again</button>
      </div>
    );
  }
  const fr = data.first_response;
  const top = data.people.slice(0, 6);
  return (
    <section className="haip-card p-5 space-y-4" aria-label="Inbox analytics">
      <div>
        <h2 className="text-sm font-semibold text-[var(--haip-fg)]">Inbox: last {data.period.days} days</h2>
        <p className="text-xs text-[var(--haip-fg-subtle)]">How fast guests on WhatsApp got a first answer, who answered, and what messages cost.</p>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div><p className="text-[11px] text-[var(--haip-fg-muted)]">Median first reply</p><p className="text-xl font-bold tabular-nums">{duration(fr.median_seconds)}</p><p className="text-[11.5px] text-[var(--haip-fg-subtle)]">{fr.turns.toLocaleString()} guest messages</p></div>
        <div><p className="text-[11px] text-[var(--haip-fg-muted)]">Slowest 10%</p><p className="text-xl font-bold tabular-nums">{duration(fr.p90_seconds)}</p><p className="text-[11.5px] text-[var(--haip-fg-subtle)]">90th percentile</p></div>
        <div><p className="text-[11px] text-[var(--haip-fg-muted)]">Answered in 15 min</p><p className="text-xl font-bold tabular-nums">{fr.within_pct?.["15"] ?? "—"}{fr.within_pct?.["15"] != null ? "%" : ""}</p><p className="text-[11.5px] text-[var(--haip-fg-subtle)]">{fr.answered_pct ?? "—"}{fr.answered_pct != null ? "%" : ""} answered at all</p></div>
        <div><p className="text-[11px] text-[var(--haip-fg-muted)]">WhatsApp cost</p><p className="text-xl font-bold tabular-nums">{rupees(data.cost.amount_inr)}</p><p className="text-[11.5px] text-[var(--haip-fg-subtle)]">{data.cost.messages.toLocaleString()} paid messages, estimate</p></div>
      </div>
      {top.length > 0 ? (
        <table className="w-full text-xs">
          <caption className="sr-only">Conversations answered per team member</caption>
          <thead><tr className="text-left text-[var(--haip-fg-muted)]"><th className="py-1.5 font-medium">Team member</th><th className="py-1.5 font-medium text-right">Conversations</th><th className="py-1.5 font-medium text-right">Messages</th></tr></thead>
          <tbody>
            {top.map(p => (
              <tr key={p.user_id} className="border-t border-[var(--haip-border)]">
                <td className="py-2 text-[var(--haip-fg)]">{p.name}</td>
                <td className="py-2 text-right tabular-nums">{p.conversations.toLocaleString()}</td>
                <td className="py-2 text-right tabular-nums">{p.messages.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-xs text-[var(--haip-fg-subtle)]">No team replies on WhatsApp in this period.</p>
      )}
    </section>
  );
}
