"use client";
// The top of the phone lead page (approved mockup "A lead"): who, stage · owner · channel (stage and owner open their sheets),
// and what they want as chips: where, when, how many. What is still missing shows as a chip too ("no return date",
// "no budget"), so the next question to ask is visible. Plus the won / lost reason card on a closed lead (lead_outcome,
// GET /leads/{id}/outcome, the same query the Won / Lost dialog reads). Pure display: every value comes from the lead page's
// own payloads (GET /leads/{id}, /feed).
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ChevronDown } from "@/lib/icons";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { RowTag } from "@/components/ui/kit";
import { channelName, istDate, nights } from "@/components/leads/lead-page/format";
import type { OutcomeView } from "@/components/leads/lead-page/OutcomeSheet";
import type { LeadDetail, LeadFeed } from "@/components/leads/lead-page/types";

export interface TripChip { text: string; missing?: boolean }

/** Where / when / who, then what is missing. Destination: the route's first stop, else the first route or property asked
 *  about, else the occasion. */
export function tripChips(lead: LeadDetail, feed?: LeadFeed): TripChip[] {
  const out: TripChip[] = [];
  const where = feed?.trip.route?.split(",")[0]?.trim() || lead.property_interest?.[0] || null;
  if (where) out.push({ text: where });
  if (lead.check_in) {
    const n = nights(lead.check_in, lead.check_out);
    out.push({ text: lead.check_out ? `${istDate(lead.check_in)}${n != null ? ` · ${n} night${n === 1 ? "" : "s"}` : ""}` : istDate(lead.check_in) });
  }
  const party = [lead.adults ? `${lead.adults} adult${lead.adults === 1 ? "" : "s"}` : null,
    lead.children ? `${lead.children} child${lead.children === 1 ? "" : "ren"}` : null].filter(Boolean).join(", ");
  if (party) out.push({ text: party });
  if (lead.occasion && lead.occasion !== where) out.push({ text: lead.occasion });
  if (lead.guest_location) out.push({ text: `from ${lead.guest_location}` });
  if (!lead.check_in) out.push({ text: "no dates", missing: true });
  else if (!lead.check_out) out.push({ text: "no return date", missing: true });
  if (!party) out.push({ text: "no guest count", missing: true });
  if (!lead.budget_estimate && !lead.budget_range_label && !lead.quoted_amount) out.push({ text: "no budget", missing: true });
  return out;
}

const chip = "inline-flex min-h-11 max-w-full items-center gap-1 truncate rounded-full px-1 text-[13px] font-semibold";

export function LeadHero({ lead, feed, stageLabel, canEdit, onStage, onOwner }: {
  lead: LeadDetail; feed?: LeadFeed; stageLabel: string; canEdit: boolean; onStage: () => void; onOwner: () => void;
}) {
  const raw = feed?.contact.first_touch_channel && feed.contact.first_touch_channel !== "other" ? feed.contact.first_touch_channel : feed?.channels[0]?.channel;
  const channel = channelName(raw);
  return (
    <div className="grid gap-2">
      <div className="flex min-w-0 items-center gap-3">
        <GuestAvatar name={lead.display_name} size="lg" />
        <div className="grid min-w-0 flex-1">
          <h1 className="haip-page-title haip-page-title--keep truncate text-[20px] leading-tight">{lead.display_name}</h1>
          <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-[var(--haip-fg-subtle)]">
            <button type="button" onClick={onStage} disabled={!canEdit} aria-haspopup="dialog" aria-label={`Stage: ${stageLabel || "none"}`} className={`${chip} text-primary disabled:opacity-90`}>
              {stageLabel || "No stage"}{canEdit && <ChevronDown size={13} aria-hidden />}
            </button>
            <span aria-hidden>·</span>
            <button type="button" onClick={onOwner} disabled={!canEdit} aria-haspopup="dialog" aria-label={`Owner: ${lead.assigned_agent_name || "nobody"}`} className={`${chip} text-[var(--haip-fg-2)] disabled:opacity-90`}>
              {lead.assigned_agent_name || "No owner"}{canEdit && <ChevronDown size={13} aria-hidden />}
            </button>
            {channel && <><span aria-hidden>·</span><span className="text-[13px]">{channel}</span></>}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5" aria-label="Trip">
        {tripChips(lead, feed).map(c => <RowTag key={c.text} tone={c.missing ? "warning" : "neutral"}>{c.text}</RowTag>)}
      </div>
    </div>
  );
}

/** Why a closed lead was won or lost, as recorded (reason + note); "Not recorded" when nobody gave one. */
export function OutcomeReasonCard({ inquiryId, kind }: { inquiryId: string; kind: "won" | "lost" }) {
  const q = useQuery<OutcomeView>({
    queryKey: ["lead-outcome", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}/outcome`).then(r => r.data), staleTime: 60_000,
  });
  const label = q.data?.reason ? q.data.catalogue?.[kind]?.find(o => o.key === q.data!.reason)?.label ?? q.data.reason.replace(/_/g, " ") : null;
  return (
    <section aria-label={kind === "won" ? "Why they booked" : "Why it was lost"}
      className="grid gap-1 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2.5 text-[13.5px]">
      <span className="text-[12px] font-bold text-[var(--haip-fg-subtle)]">{kind === "won" ? "Why they booked" : "Why it was lost"}</span>
      {q.isPending ? <span className="text-[var(--haip-fg-subtle)]">Loading…</span>
        : q.isError ? <button type="button" onClick={() => q.refetch()} className="min-h-11 justify-self-start font-semibold text-primary">Couldn&apos;t load. Try again</button>
          : <span className="text-[var(--haip-fg)]">{label ?? "Not recorded"}{q.data?.note ? <span className="text-[var(--haip-fg-2)]"> · {q.data.note}</span> : null}</span>}
    </section>
  );
}
