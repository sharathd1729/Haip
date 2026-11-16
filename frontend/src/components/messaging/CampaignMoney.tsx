"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, IndianRupee, Link2, Loader2, RotateCcw, UserPlus, Wallet } from "@/lib/icons";
import { cn, formatINR } from "@/lib/utils";
import api from "@/lib/api";

/** What a campaign earned: taps on the tracked link, leads, bookings, revenue and WhatsApp cost
 *  (backend services/wa_campaign_money.py), plus "send again to…" retarget drafts. */
export interface CampaignMoneyData {
  tracked_link: boolean;
  clicks: number | null;
  click_rate: number | null;
  leads: number;
  bookings: number;
  revenue_inr: number | null;
  money_restricted: boolean;
  cost_inr: number;
  billable_messages: number;
  cost_per_lead_inr: number | null;
  cost_per_booking_inr: number | null;
  attribution_days: number;
}

interface Segment { segment: string; label: string; count: number }

// Message costs are paise-level: keep two decimals (formatINR rounds to whole rupees).
const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

function Figure({ label, value, sub, icon }: { label: string; value: string; sub?: string; icon: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-[var(--haip-fg-muted)]">{icon}{label}</div>
      <p className="text-xl font-bold text-[var(--haip-fg)] mt-0.5 tabular-nums truncate">{value}</p>
      {sub && <p className="text-[11.5px] text-[var(--haip-fg-subtle)]">{sub}</p>}
    </div>
  );
}

export function CampaignMoney({ campaignId, money, onRetargeted }: {
  campaignId: string; money: CampaignMoneyData; onRetargeted?: (name: string) => void;
}) {
  const queryClient = useQueryClient();
  const [made, setMade] = useState("");
  const { data: segments = [] } = useQuery<Segment[]>({
    queryKey: ["wa-campaign-retarget", campaignId],
    queryFn: () => api.get(`/messaging/campaigns/${campaignId}/retarget`).then(r => r.data),
    staleTime: 30_000,
  });
  const retarget = useMutation({
    mutationFn: (segment: string) => api.post(`/messaging/campaigns/${campaignId}/retarget`, { segment }).then(r => r.data),
    onSuccess: (c: { name: string }) => {
      setMade(c.name);
      queryClient.invalidateQueries({ queryKey: ["wa-campaigns"] });
      onRetargeted?.(c.name);
    },
  });

  const cost = rupees(money.cost_inr);
  return (
    <section className="rounded-2xl border border-[var(--haip-border)] p-4 space-y-4" aria-label="What this campaign earned">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <Figure label="Link taps" icon={<Link2 size={12} />}
          value={money.tracked_link ? (money.clicks ?? 0).toLocaleString() : "Not tracked"}
          sub={money.tracked_link ? (money.click_rate !== null ? `${money.click_rate}% of sent` : undefined) : "Use a tracked link button"} />
        <Figure label="New leads" icon={<UserPlus size={12} />} value={money.leads.toLocaleString()}
          sub="shared a number after the message" />
        <Figure label="Bookings" icon={<CalendarCheck size={12} />} value={money.bookings.toLocaleString()}
          sub={`within ${money.attribution_days} days`} />
        <Figure label="Revenue" icon={<IndianRupee size={12} />}
          value={money.money_restricted ? "Hidden" : formatINR(money.revenue_inr ?? 0)}
          sub={money.money_restricted ? "needs revenue access" : "cancelled bookings left out"} />
        <Figure label="WhatsApp cost" icon={<Wallet size={12} />} value={cost}
          sub={money.cost_per_lead_inr !== null ? `${rupees(money.cost_per_lead_inr)} per lead` : `${money.billable_messages.toLocaleString()} paid messages`} />
      </div>
      <p className="text-[11px] text-[var(--haip-fg-subtle)]">
        Cost is an estimate from Meta&apos;s pricing on each message and your rates in Marketing settings; Meta&apos;s invoice is final.
        Leads and bookings are people this campaign reached who became a lead or booked afterwards.
      </p>

      {segments.some(s => s.count > 0) && (
        <div className="border-t border-[var(--haip-border)] pt-3">
          <p className="text-xs font-semibold text-[var(--haip-fg-2)] mb-2 flex items-center gap-1.5"><RotateCcw size={12} /> Send a follow-up to</p>
          <div className="flex flex-wrap gap-2">
            {segments.filter(s => s.count > 0).map(s => (
              <button key={s.segment} type="button" disabled={retarget.isPending}
                onClick={() => retarget.mutate(s.segment)}
                className={cn("min-h-11 flex items-center gap-1.5 px-3 rounded-full text-xs font-medium border border-[var(--haip-border)]",
                  "text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] active:scale-[0.98] transition-transform disabled:opacity-50")}>
                {retarget.isPending && retarget.variables === s.segment && <Loader2 size={12} className="animate-spin" />}
                {s.label} <span className="tabular-nums text-[var(--haip-fg-subtle)]">{s.count.toLocaleString()}</span>
              </button>
            ))}
          </div>
          {made && <p className="text-[11.5px] text-[var(--haip-status-success-fg)] mt-2">Draft &ldquo;{made}&rdquo; created. Review and launch it from the campaign list.</p>}
          {retarget.isError && <p className="text-[11.5px] text-[var(--haip-status-danger-fg)] mt-2">Couldn&apos;t create the follow-up. Try again.</p>}
          <p className="text-[11px] text-[var(--haip-fg-subtle)] mt-2">People who opted out or withdrew marketing consent are always left out.</p>
        </div>
      )}
    </section>
  );
}
