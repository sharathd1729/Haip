"use client";
// Where new leads first came from, and what Meta Ads cost. Sources follow the PERSON's first touch (a lead who returns through
// another platform is not moved); a person whose first touch is unknown is shown as Unknown. Meta's own numbers sit apart from
// what HAIP can verify.
// Lists reflow into stacked rows on a phone (no sideways scrolling) and become aligned columns from the tablet width.
import type { ReactNode } from "react";
import Link from "next/link";
import { Empty, NotAvailable, Row, SectionTitle } from "./parts";
import { ago, inr, isRestricted, num, pct, type BusinessOverview, type MetaAds, type SourceRow } from "./types";

export function Acquisition({ data }: { data: BusinessOverview }) {
  const bookings = data.access.bookings, money = data.access.revenue;
  const unlinked = !isRestricted(data.bookings) ? data.bookings.no_identified_lead : null;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Sources rows={data.sources} bookings={bookings} money={money} unlinked={unlinked} />
      {data.meta_ads && <Meta meta={data.meta_ads} bookings={bookings} />}
    </div>
  );
}

export function Bar({ value, max }: { value: number; max: number }) {
  return (
    <span className="mt-1 block h-1.5 overflow-hidden rounded-sm bg-[var(--haip-surface)]" aria-hidden>
      <span className="block h-full rounded-sm bg-primary/60 motion-safe:transition-[width] motion-safe:duration-300" style={{ width: `${max ? Math.max(value ? 4 : 0, (value / max) * 100) : 0}%` }} />
    </span>
  );
}

/** Column headings, shown from the tablet width; on a phone every figure carries its own small label instead. */
export function ListHead({ cols }: { cols: string[] }) {
  return (
    <div className="hidden grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))] gap-x-3 border-b border-[var(--haip-border)] pb-1.5 text-[11.5px] font-semibold text-[var(--haip-fg-subtle)] md:grid">
      <span>{cols[0]}</span>{cols.slice(1).map(c => <span key={c} className="text-right">{c}</span>)}
    </div>
  );
}

export function Cell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="min-w-0 text-[13px] tabular-nums text-[var(--haip-fg)] md:text-right">
      <span className="block text-[11px] text-[var(--haip-fg-subtle)] md:hidden">{label}</span>{children}
    </span>
  );
}

export const ROW = "grid grid-cols-3 gap-x-3 gap-y-1 py-2.5 md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))] md:items-center";

function Sources({ rows, bookings, money, unlinked }: { rows: SourceRow[]; bookings: boolean; money: boolean; unlinked: number | null }) {
  const max = Math.max(1, ...rows.map(r => r.leads));
  return (
    <section aria-labelledby="sources-title" className="haip-card px-4 py-4 sm:px-6 sm:py-5 lg:col-span-2">
      <SectionTitle sub="New leads (people) by where they first got in touch; bookings and value are those made by the same people">
        <span id="sources-title">Sources</span>
      </SectionTitle>
      {rows.length === 0 ? <Empty>No new leads in this period.</Empty> : (
        <>
          <ListHead cols={["Source", "Leads", "Bookings", "Booked value"]} />
          <ul className="divide-y divide-[var(--haip-border)]">
            {rows.map(r => (
              <li key={r.key} className={ROW}>
                <span className="col-span-3 min-w-0 text-[13px] font-medium text-[var(--haip-fg)] md:col-span-1">{r.label}<Bar value={r.leads} max={max} /></span>
                <Cell label="Leads">{num(r.leads)}</Cell>
                <Cell label="Bookings">{bookings ? num(r.bookings) : "—"}</Cell>
                <Cell label="Booked value">{money && bookings ? inr(r.booking_value) : "—"}</Cell>
              </li>
            ))}
          </ul>
        </>
      )}
      {unlinked != null && unlinked > 0 && (
        <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">{num(unlinked)} booking{unlinked === 1 ? "" : "s"} made in this period {unlinked === 1 ? "is" : "are"} from a guest with no phone number on file, so {unlinked === 1 ? "it is" : "they are"} not credited to any source above.</p>
      )}
    </section>
  );
}

function Meta({ meta, bookings }: { meta: MetaAds; bookings: boolean }) {
  return (
    <section aria-labelledby="meta-title" className="haip-card px-4 py-4 sm:px-6 sm:py-5">
      <SectionTitle sub="What Meta reports, kept apart from what HAIP can verify"
        actions={<Link href="/dashboard/marketing" className="inline-flex min-h-11 items-center text-[12.5px] font-semibold text-primary hover:underline lg:min-h-0">Marketing</Link>}>
        <span id="meta-title">Meta Ads</span>
      </SectionTitle>
      {!meta.configured ? <Empty>No ad account is connected.</Empty> : (
        <>
          <p className="text-[11.5px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Reported by Meta</p>
          <dl className="divide-y divide-[var(--haip-border)]">
            <Row label="Spend" value={inr(meta.spend)} />
            <Row label="Impressions" value={num(meta.impressions)} />
            <Row label="Clicks" value={num(meta.clicks)} hint={`click rate ${pct(meta.ctr)}`} />
            <Row label="Cost per click" value={inr(meta.cpc)} />
            <Row label="Cost per 1,000 shown" value={inr(meta.cpm)} />
            <Row label="Chats started" value={num(meta.reported_chats)} />
          </dl>
          <p className="mt-4 text-[11.5px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Verified in HAIP</p>
          <dl className="divide-y divide-[var(--haip-border)]">
            <Row label="Chats traced to an ad" value={num(meta.verified_conversations)} hint={(meta.not_traced ?? 0) > 0 ? `${num(meta.not_traced)} of Meta’s chats could not be traced` : undefined} />
            <Row label="People in those chats" value={num(meta.verified_contacts)} />
            <Row label="Leads (phone number held)" value={num(meta.verified_leads)} hint={meta.cost_per_verified_lead != null ? `${inr(meta.cost_per_verified_lead)} each` : undefined} />
            {bookings && <Row label="Bookings linked to them" value={num(meta.verified_bookings)} hint="any date, not only this period" />}
            {bookings && <Row label="Booked value" value={inr(meta.verified_booking_value)} hint={meta.return_on_spend != null ? `${meta.return_on_spend}× the spend` : undefined} />}
          </dl>
          {(meta.not_traced ?? 0) > 0 && (
            <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">Leads and bookings above are a floor: only chats whose ad referral HAIP recorded can be counted.</p>
          )}
          {(meta.campaigns?.length ?? 0) > 0 && (
            <div className="mt-4 border-t border-[var(--haip-border)] pt-3">
              <h3 className="text-[12.5px] font-semibold text-[var(--haip-fg)]">Top campaigns by spend</h3>
              <ul className="divide-y divide-[var(--haip-border)]">
                {meta.campaigns!.map(c => (
                  <li key={c.campaign_id || c.name} className="py-2">
                    <p className="truncate text-[13px] font-medium text-[var(--haip-fg)]">{c.name}</p>
                    <p className="text-[12px] tabular-nums text-[var(--haip-fg-subtle)]">
                      {inr(c.spend)} · {num(c.reported_chats)} chats (Meta) · {num(c.verified_conversations)} traced in HAIP
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {meta.last_error ? <NotAvailable label="Latest sync" reason={meta.last_error} /> : meta.last_synced_at && (
            <p className="mt-2 text-[11.5px] text-[var(--haip-fg-subtle)]">Meta data synced {ago(meta.last_synced_at)} ago.</p>
          )}
        </>
      )}
    </section>
  );
}
