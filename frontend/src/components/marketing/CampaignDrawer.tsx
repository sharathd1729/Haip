"use client";
// Everything about one campaign: its status and budget, every number Meta gives, what HAIP saw after the click,
// and each ad with its creative and audience.
import type { ReactNode } from "react";
import { Drawer, StatusPill } from "@/components/ui/kit";
import {
  budgetLabel, longDate, money, money2, num, objectiveLabel, pct, statusLabel, times,
  type AdDetail, type Audience, type Campaign, type Measures, type Results, type Status,
} from "./ads";

function Fact({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 rounded-lg bg-[var(--haip-surface)] px-3 py-2" title={hint}>
      <dt className="truncate text-[11px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{label}</dt>
      <dd className="mt-0.5 text-[15px] font-semibold tabular-nums text-[var(--haip-fg)] [overflow-wrap:anywhere]">{value}</dd>
    </div>
  );
}

function Facts({ m, r }: { m: Measures; r: Results }) {
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      <Fact label="Spend" value={money(m.spend)} />
      <Fact label="Impressions" value={num(m.impressions)} hint="Times the ad was shown" />
      <Fact label="Clicks" value={num(m.clicks)} hint="All clicks on the ad" />
      <Fact label="Link clicks" value={num(m.link_clicks)} />
      <Fact label="Click rate" value={pct(m.ctr)} hint="Clicks ÷ impressions" />
      <Fact label="Cost per 1,000 shown" value={money2(m.cpm)} hint="CPM" />
      <Fact label="Cost per click" value={money2(m.cpc)} />
      <Fact label="Engagements" value={num(m.post_engagement)} hint="Reactions, comments, shares, saves" />
      <Fact label="Video views" value={num(m.video_views)} />
      <Fact label="Chats started" value={num(m.meta_conversations)} hint="Counted by Meta" />
      <Fact label="First replies" value={num(m.first_replies)} hint="Chats where the business replied" />
      <Fact label="Cost per chat" value={money2(m.cost_per_conversation)} />
      <Fact label="Leads in HAIP" value={num(r.haip_leads)} hint="Leads HAIP traced to these ads" />
      <Fact label="Cost per lead" value={money(r.cost_per_lead)} />
      <Fact label="Bookings" value={num(r.bookings)} />
      <Fact label="Revenue" value={money(r.revenue)} />
      <Fact label="Return on spend" value={times(r.roas)} hint="Revenue ÷ spend" />
    </dl>
  );
}

function About({ s }: { s: Status }) {
  const st = statusLabel(s.effective_status || s.status);
  const bits = [objectiveLabel(s.objective), budgetLabel(s),
    s.starts_at ? `Started ${longDate(s.starts_at)}` : null, s.ends_at ? `Ends ${longDate(s.ends_at)}` : null].filter(Boolean);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-[var(--haip-fg-2)]">
      {st && <StatusPill tone={st.tone}>{st.label}</StatusPill>}
      {bits.map((b, i) => <span key={i}>{b}</span>)}
    </div>
  );
}

function AudienceChips({ a }: { a: Audience }) {
  const chips = [a.ages && `Ages ${a.ages}`, a.genders.join(", "), ...a.places, ...a.interests, ...a.platforms].filter(Boolean) as string[];
  if (chips.length === 0) return null;
  return <p className="flex flex-wrap gap-1.5">{chips.map((c, i) => <StatusPill key={`${c}-${i}`} tone="neutral">{c}</StatusPill>)}</p>;
}

function AdCard({ ad }: { ad: AdDetail }) {
  const st = statusLabel(ad.effective_status || ad.status);
  const img = ad.creative?.thumbnail_url || ad.creative?.image_url;
  return (
    <article className="space-y-2.5 rounded-xl border border-[var(--haip-border)] p-3">
      <div className="flex gap-3">
        {img
          // eslint-disable-next-line @next/next/no-img-element
          ? <img src={img} alt="" referrerPolicy="no-referrer" loading="lazy" className="size-16 flex-shrink-0 rounded-lg object-cover" />
          : <div className="flex size-16 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--haip-surface)] text-xs text-[var(--haip-fg-subtle)]" aria-hidden>No image</div>}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="truncate text-sm font-bold text-[var(--haip-fg)]">{ad.name}</h4>
            {st && <StatusPill tone={st.tone}>{st.label}</StatusPill>}
          </div>
          {ad.creative?.title && <p className="mt-0.5 text-sm font-semibold text-[var(--haip-fg-2)] [overflow-wrap:anywhere]">{ad.creative.title}</p>}
          {ad.creative?.body && <p className="mt-0.5 line-clamp-3 text-xs text-[var(--haip-fg-subtle)] [overflow-wrap:anywhere]">{ad.creative.body}</p>}
          {ad.adset_name && <p className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Ad set: {ad.adset_name}</p>}
        </div>
      </div>
      {ad.audience && <AudienceChips a={ad.audience} />}
      <p className="text-xs tabular-nums text-[var(--haip-fg-2)]">
        {money(ad.spend)} spent · {num(ad.impressions)} shown · {num(ad.clicks)} clicks ({pct(ad.ctr)}) · {num(ad.meta_conversations)} chats
        {ad.haip_leads > 0 || ad.bookings > 0 ? ` · ${num(ad.haip_leads)} leads · ${num(ad.bookings)} bookings · ${money(ad.revenue)} · ${times(ad.roas)}` : ""}
      </p>
    </article>
  );
}

export function CampaignDrawer({ campaign, rangeLabel, onClose }: { campaign: Campaign | null; rangeLabel: string; onClose: () => void }) {
  return (
    <Drawer open={!!campaign} onOpenChange={o => { if (!o) onClose(); }} wide
      title={campaign?.campaign_name ?? ""} description={campaign ? `${rangeLabel} · ${campaign.ads} ad${campaign.ads === 1 ? "" : "s"}` : undefined}>
      {campaign && (
        <div className="space-y-5">
          <About s={campaign} />
          <Facts m={campaign} r={campaign} />
          <section aria-label="Ads" className="space-y-3">
            <h3 className="text-sm font-bold text-[var(--haip-fg)]">Ads in this campaign</h3>
            {campaign.ad_details.length === 0
              ? <p className="text-sm text-[var(--haip-fg-subtle)]">No ads ran in this period.</p>
              : campaign.ad_details.map(a => <AdCard key={a.ad_id} ad={a} />)}
          </section>
        </div>
      )}
    </Drawer>
  );
}
