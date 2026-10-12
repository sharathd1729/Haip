"use client";
// Where leads and bookings come from, what Meta Ads cost, and who is converting. Attribution is stated for what it
// is: a booking counts for a source or an agent only when it is linked to a lead; Meta's own numbers sit apart from
// what HAIP can verify.
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Empty, NotAvailable, Row, SectionTitle } from "./parts";
import { ago, inr, isRestricted, num, type AgentRow, type BusinessOverview, type MetaAds, type SourceRow } from "./types";

export function Acquisition({ data }: { data: BusinessOverview }) {
  const money = data.access.revenue;
  const bookings = data.access.bookings;
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <div className="space-y-5 lg:col-span-2">
        <Sources rows={data.sources} bookings={bookings} money={money} unlinked={!isRestricted(data.bookings) ? data.bookings.not_linked_to_a_lead : null} />
        {data.agents && <Agents rows={data.agents} bookings={bookings} money={money} />}
      </div>
      {data.meta_ads && <Meta meta={data.meta_ads} bookings={bookings} />}
    </div>
  );
}

function Bar({ value, max }: { value: number; max: number }) {
  return (
    <span className="mt-1 block h-1.5 overflow-hidden rounded-sm bg-[var(--haip-surface)]" aria-hidden>
      <span className="block h-full rounded-sm bg-primary/60 motion-safe:transition-[width] motion-safe:duration-300" style={{ width: `${max ? Math.max(value ? 4 : 0, (value / max) * 100) : 0}%` }} />
    </span>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th scope="col" className={cn("pb-2 text-[11.5px] font-semibold text-[var(--haip-fg-subtle)]", right ? "text-right" : "text-left")}>{children}</th>;
}

function Sources({ rows, bookings, money, unlinked }: { rows: SourceRow[]; bookings: boolean; money: boolean; unlinked: number | null }) {
  const max = Math.max(1, ...rows.map(r => r.leads));
  return (
    <section aria-labelledby="sources-title" className="haip-card px-5 py-5 sm:px-6">
      <SectionTitle sub="Leads by where they first came from; bookings and value only where a booking is linked to the lead">
        <span id="sources-title">Sources</span>
      </SectionTitle>
      {rows.length === 0 ? <Empty>No leads in this period.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-[13px]">
            <thead><tr><Th>Source</Th><Th right>Leads</Th><Th right>Bookings</Th><Th right>Booked value</Th></tr></thead>
            <tbody className="divide-y divide-[var(--haip-border)]">
              {rows.map(r => (
                <tr key={r.key}>
                  <td className="w-[40%] py-2 pr-3"><span className="text-[var(--haip-fg)]">{r.label}</span><Bar value={r.leads} max={max} /></td>
                  <td className="py-2 text-right tabular-nums">{num(r.leads)}</td>
                  <td className="py-2 text-right tabular-nums">{bookings ? num(r.bookings) : "—"}</td>
                  <td className="py-2 text-right tabular-nums">{money && bookings ? inr(r.booking_value) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {unlinked != null && unlinked > 0 && (
        <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">{num(unlinked)} booking{unlinked === 1 ? "" : "s"} made in this period {unlinked === 1 ? "is" : "are"} not linked to a lead, so {unlinked === 1 ? "it is" : "they are"} not credited to any source above.</p>
      )}
    </section>
  );
}

function Agents({ rows, bookings, money }: { rows: AgentRow[]; bookings: boolean; money: boolean }) {
  return (
    <section aria-labelledby="agents-title" className="haip-card px-5 py-5 sm:px-6">
      <SectionTitle sub="Credited to whoever owns the lead now; only bookings linked to a lead count"
        actions={<Link href="/dashboard/operations" className="inline-flex min-h-11 items-center text-[12.5px] font-semibold text-primary hover:underline sm:min-h-0">Response times and calls</Link>}>
        <span id="agents-title">Team</span>
      </SectionTitle>
      {rows.length === 0 ? <Empty>No leads in this period.</Empty> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-[13px]">
            <thead><tr><Th>Agent</Th><Th right>Leads</Th><Th right>Bookings</Th><Th right>Booked value</Th></tr></thead>
            <tbody className="divide-y divide-[var(--haip-border)]">
              {rows.map(r => (
                <tr key={r.agent_id ?? "none"}>
                  <td className={cn("py-2 pr-3", r.agent_id ? "text-[var(--haip-fg)]" : "text-[var(--haip-fg-subtle)]")}>{r.name}</td>
                  <td className="py-2 text-right tabular-nums">{num(r.leads)}</td>
                  <td className="py-2 text-right tabular-nums">{bookings ? num(r.bookings) : "—"}</td>
                  <td className="py-2 text-right tabular-nums">{money && bookings ? inr(r.booking_value) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Meta({ meta, bookings }: { meta: MetaAds; bookings: boolean }) {
  return (
    <section aria-labelledby="meta-title" className="haip-card px-5 py-5 sm:px-6">
      <SectionTitle sub="What Meta reports, kept apart from what HAIP can verify"
        actions={<Link href="/dashboard/marketing" className="inline-flex min-h-11 items-center text-[12.5px] font-semibold text-primary hover:underline sm:min-h-0">Marketing</Link>}>
        <span id="meta-title">Meta Ads</span>
      </SectionTitle>
      {!meta.configured ? <Empty>No ad account is connected.</Empty> : (
        <>
          <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Reported by Meta</p>
          <dl className="divide-y divide-[var(--haip-border)]">
            <Row label="Spend" value={inr(meta.spend)} />
            <Row label="Chats started" value={num(meta.reported_chats)} />
          </dl>
          <p className="mt-4 text-[11.5px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Verified in HAIP</p>
          <dl className="divide-y divide-[var(--haip-border)]">
            <Row label="Chats traced to an ad" value={num(meta.verified_conversations)} hint={(meta.not_traced ?? 0) > 0 ? `${num(meta.not_traced)} of Meta’s chats could not be traced` : undefined} />
            <Row label="Leads" value={num(meta.verified_leads)} hint={meta.cost_per_verified_lead != null ? `${inr(meta.cost_per_verified_lead)} each` : undefined} />
            {bookings && <Row label="Bookings linked to them" value={num(meta.verified_bookings)} hint="any date, not only this period" />}
            {bookings && <Row label="Booked value" value={inr(meta.verified_booking_value)} hint={meta.return_on_spend != null ? `${meta.return_on_spend}× the spend` : undefined} />}
          </dl>
          {(meta.not_traced ?? 0) > 0 && (
            <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">Leads and bookings above are a floor: only chats whose ad referral HAIP recorded can be counted.</p>
          )}
          {meta.last_error ? <NotAvailable label="Latest sync" reason={meta.last_error} /> : meta.last_synced_at && (
            <p className="mt-2 text-[11.5px] text-[var(--haip-fg-subtle)]">Meta data synced {ago(meta.last_synced_at)} ago.</p>
          )}
        </>
      )}
    </section>
  );
}
