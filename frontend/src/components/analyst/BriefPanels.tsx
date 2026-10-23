"use client";
// The brief's sections (read-only), shared by the Analyst page and the signed report link. Every number shown here comes
// from the backend (computed facts, or brief text whose numbers were checked against them).
import type { ReactNode } from "react";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { CheckCircle, AlertTriangle, IndianRupee, MapPin, Users } from "@/lib/icons";
import { formatINR } from "@/lib/utils";
import type { Brief, Facts } from "./types";

function List({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-[var(--haip-fg-subtle)]">{empty}</p>;
  return <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--haip-fg)]">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>;
}

function Section({ title, icon, children, note }: { title: string; icon?: typeof Users; children: ReactNode; note?: string }) {
  return (
    <Card>
      <CardHeader icon={icon} title={title} description={note} tone="plain" />
      <CardBody>{children}</CardBody>
    </Card>
  );
}

export function WorkingPanels({ brief, periodLabel }: { brief: Brief; periodLabel: string }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Section title="What's working" icon={CheckCircle} note={periodLabel}><List items={brief.working} empty="Nothing stood out." /></Section>
      <Section title="What's not working" icon={AlertTriangle} note={periodLabel}><List items={brief.not_working} empty="Nothing stood out." /></Section>
    </div>
  );
}

export function ReasonsPanels({ brief }: { brief: Brief }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {brief.why_lost && <Section title="Why enquiries were lost"><p className="text-sm text-[var(--haip-fg)]">{brief.why_lost}</p></Section>}
      {brief.why_dms_not_leads && <Section title="Why DMs did not become leads"><p className="text-sm text-[var(--haip-fg)]">{brief.why_dms_not_leads}</p></Section>}
    </div>
  );
}

export function TeamTable({ facts, summary, periodLabel }: { facts: Facts; summary?: string; periodLabel: string }) {
  const rows = facts.team.filter(r => r.leads + r.calls_received + r.outbound_made + r.followups_due > 0);
  return (
    <Section title="Team" icon={Users} note={periodLabel}>
      {rows.length === 0 ? <p className="text-sm text-[var(--haip-fg-subtle)]">No team activity in this period.</p> : (
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[560px] text-left text-sm">
            <thead className="text-xs text-[var(--haip-fg-subtle)]">
              <tr><th className="py-2 pr-3 font-medium">Person</th><th className="pr-3 font-medium">Leads</th><th className="pr-3 font-medium">Booked</th>
                <th className="pr-3 font-medium">Calls in / missed not returned</th><th className="pr-3 font-medium">Calls out / connected</th>
                <th className="pr-3 font-medium">First contact</th><th className="font-medium">Follow-ups on time</th></tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.user_id ?? "none"} className="border-t border-[var(--haip-border)]">
                  <td className="py-2 pr-3 font-semibold text-[var(--haip-fg)]">{r.name}</td>
                  <td className="pr-3">{r.leads}</td><td className="pr-3">{r.booked}</td>
                  <td className="pr-3">{r.calls_received} / {r.missed_not_returned}</td>
                  <td className="pr-3">{r.outbound_made} / {r.outbound_connected}</td>
                  <td className="pr-3">{r.first_contact_minutes === null ? "No data" : `${r.first_contact_minutes} min`}</td>
                  <td>{r.followups_due ? `${r.followups_on_time} of ${r.followups_due}` : "None due"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {summary && <p className="mt-2 text-sm text-[var(--haip-fg-muted)]">{summary}</p>}
    </Section>
  );
}

export function DemandMoney({ brief, facts, periodLabel }: { brief: Brief; facts: Facts; periodLabel: string }) {
  const rev = facts.journey.revenue;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Section title="Demand" icon={MapPin} note={periodLabel}>
        {brief.demand && <p className="mb-2 text-sm text-[var(--haip-fg)]">{brief.demand}</p>}
        <div className="flex flex-wrap gap-1.5">
          {facts.demand.routes_asked.map(r => <StatusPill key={r.label} tone="brand">{r.label} · {r.count}</StatusPill>)}
          {facts.demand.unavailable_asks.map(r => <StatusPill key={`u-${r.label}`} tone="warning">Not offered: {r.label} · {r.count}</StatusPill>)}
        </div>
      </Section>
      <Section title="Money" icon={IndianRupee} note={periodLabel}>
        {rev.restricted ? <p className="text-sm text-[var(--haip-fg-subtle)]">You don&apos;t have access to revenue figures.</p> : (
          <>
            <p className="text-sm text-[var(--haip-fg)]">{rev.bookings ?? 0} bookings · booked {formatINR(rev.booked_value ?? 0)} · collected {formatINR(rev.collected ?? 0)}</p>
            {brief.money && <p className="mt-2 text-sm text-[var(--haip-fg-muted)]">{brief.money}</p>}
          </>
        )}
        {facts.journey.ads.connected && (
          <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">Ads: {formatINR(facts.journey.ads.spend)} spent, {facts.journey.ads.chats_started} chats
            {facts.journey.ads.cost_per_chat !== null ? `, ${formatINR(facts.journey.ads.cost_per_chat)} per chat` : ""}.</p>
        )}
      </Section>
    </div>
  );
}
