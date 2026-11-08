"use client";
// Website page, under the editor: what the website brought in (visits -> enquiries -> bookings by source, WhatsApp
// buttons) and the tracking settings (Meta Pixel, Conversions API, GA4, Google Ads). Backend: endpoints/website_growth.py.
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { Card, CardBody, Drawer, EmptyState } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webError } from "@/lib/website";
import { growthApi, type Tracking } from "@/lib/websiteGrowth";
import { type GadsForm, gadsForm, gadsPayload, GoogleAdsFields } from "./GoogleAdsFields";
import { PromoSheet } from "./PromoSheet";

const inr = (n: number) => "₹" + Math.round(n).toLocaleString("en-IN");

export function GrowthPanel({ canApprove }: { canApprove: boolean }) {
  const [days, setDays] = useState(30);
  const [open, setOpen] = useState(false);
  const [promos, setPromos] = useState(false);
  const report = useQuery({ queryKey: ["web-report", days], queryFn: () => growthApi.report(days) });
  const r = report.data;
  return (
    <Card>
      <CardBody className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <BarChart3 size={20} aria-hidden="true" className="text-[var(--primary)]" />
          <p className="mr-auto font-semibold">What your website brought in</p>
          <select className={`${inputCls} w-auto`} aria-label="Period" value={days} onChange={e => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
          </select>
          <Link className={btn} href="/dashboard/marketing/website/google">Google profile</Link>
          {canApprove && <button className={btn} onClick={() => setPromos(true)}>Promo codes</button>}
          {canApprove && <button className={btn} onClick={() => setOpen(true)}>Tracking</button>}
        </div>
        {report.isLoading ? <div className="h-32 animate-pulse rounded-xl bg-[var(--haip-border)]" />
          : report.isError ? <p className="text-sm">Couldn&apos;t load the numbers. <button className="underline" onClick={() => report.refetch()}>Try again</button></p>
          : !r || !r.rows.length ? <EmptyState title="No visits yet" hint="Visits, enquiries and bookings show here once guests find your website." />
          : <>
            <p className="text-sm text-[var(--haip-fg-muted)]">Since {r.since}: {r.total.visits} visits, {r.total.enquiries} enquiries, {r.total.bookings} bookings.</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-[var(--haip-fg-muted)]"><th className="py-2 pr-3 font-semibold">Came from</th>
                  <th className="py-2 pr-3 text-right font-semibold">Visits</th><th className="py-2 pr-3 text-right font-semibold">Enquiries</th>
                  <th className="py-2 pr-3 text-right font-semibold">Bookings</th>{!r.money_restricted && <th className="py-2 text-right font-semibold">Booked value</th>}</tr></thead>
                <tbody>{r.rows.map(x => (
                  <tr key={x.source} className="border-t border-[var(--haip-border)]"><td className="py-2 pr-3">{x.source}</td>
                    <td className="py-2 pr-3 text-right">{x.visits}</td><td className="py-2 pr-3 text-right">{x.enquiries}</td>
                    <td className="py-2 pr-3 text-right">{x.bookings}</td>{!r.money_restricted && <td className="py-2 text-right">{inr(x.value || 0)}</td>}</tr>))}</tbody>
              </table>
            </div>
            {r.buttons.length > 0 && <div><p className="text-sm font-semibold">WhatsApp buttons that started chats</p>
              <ul className="text-sm">{r.buttons.map(b => <li key={b.code}>{b.code}: {b.enquiries} chats, {b.bookings} booked</li>)}</ul></div>}
          </>}
      </CardBody>
      {canApprove && <TrackingSheet open={open} onClose={() => setOpen(false)} />}
      {canApprove && <PromoSheet open={promos} onClose={() => setPromos(false)} />}
    </Card>
  );
}

type Form = GadsForm & { pixel: string; ga4: string; capi: boolean; token: string; test: string; ga4Secret: string };

function TrackingSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const cur = useQuery({ queryKey: ["web-tracking"], queryFn: growthApi.tracking, enabled: open });
  const [f, setF] = useState<Form | null>(null);
  const t: Tracking | undefined = cur.data;
  const v: Form | null = f ?? (t ? { ...gadsForm(t), pixel: t.pixel_id || "", ga4: t.ga4_id || "", capi: t.capi_enabled, token: "", test: t.capi_test_code || "", ga4Secret: "" } : null);
  const save = useMutation({
    mutationFn: (x: Form) => growthApi.saveTracking({ pixel_id: x.pixel.trim() || null, ga4_id: x.ga4.trim().toUpperCase() || null,
      capi_enabled: x.capi, capi_token: x.token.trim() ? x.token.trim() : null, capi_test_code: x.test.trim().toUpperCase() || null,
      ga4_api_secret: x.ga4Secret.trim() ? x.ga4Secret.trim() : null, ...gadsPayload(x) }),
    onSuccess: d => { qc.setQueryData(["web-tracking"], { ...d, google_ads: t?.google_ads, recent: t?.recent }); setF(null); onClose(); toast({ variant: "success", title: "Saved. Your website picks it up within 5 minutes." }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: webError(e, "Check the ids and try again.") }) });
  const set = <K extends keyof Form>(k: K, val: Form[K]) => { if (v) setF({ ...v, [k]: val }); };
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) { setF(null); onClose(); } }} title="Tracking"
      footer={<div className="flex gap-2"><button className={btn} onClick={onClose}>Cancel</button>
        <button className={btnPrimary} disabled={!v || save.isPending} onClick={() => v && save.mutate(v)}>{save.isPending ? "Saving…" : "Save"}</button></div>}>
      {cur.isError ? <p className="text-sm">Couldn&apos;t load your settings. <button className="underline" onClick={() => cur.refetch()}>Try again</button></p>
        : !v ? <div className="h-40 animate-pulse rounded-xl bg-[var(--haip-border)]" /> : (
        <div className="grid gap-4 text-[15px]">
          <p className="text-sm text-[var(--haip-fg-muted)]">Guests see a cookie banner. Meta and Google load only after they tap Accept. Bookings work either way.</p>
          <label className="grid gap-1"><span className="text-sm font-semibold">Meta Pixel id</span>
            <input className={inputCls} inputMode="numeric" value={v.pixel} onChange={e => set("pixel", e.target.value)} placeholder="15 digits from Meta Events Manager" /></label>
          <label className="grid gap-1"><span className="text-sm font-semibold">Google Analytics 4 id</span>
            <input className={inputCls} value={v.ga4} onChange={e => set("ga4", e.target.value)} placeholder="G-XXXXXXX" /></label>
          {v.ga4.trim() && <label className="grid gap-1"><span className="text-sm font-semibold">GA4 Measurement Protocol secret (optional)</span>
            <input className={inputCls} type="password" autoComplete="off" value={v.ga4Secret} onChange={e => set("ga4Secret", e.target.value)}
              placeholder={t?.has_ga4_api_secret ? "Saved. Paste a new one to replace it." : "GA4 › Admin › Data streams › Measurement Protocol API secrets"} />
            <span className="text-xs text-[var(--haip-fg-muted)]">HAIP then sends each paid booking to GA4 itself, so it counts even when the guest never comes back from the payment page. Only for guests who tapped Accept. Stored encrypted; never shown again.</span></label>}
          <label className="flex min-h-11 items-center gap-3"><input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={v.capi} onChange={e => set("capi", e.target.checked)} />
            <span><b className="font-semibold">Also send from HAIP (Conversions API)</b><span className="block text-sm text-[var(--haip-fg-muted)]">Enquiries, checkouts and bookings reach Meta even when a browser blocks the pixel. Only for guests who agreed to offers.</span></span></label>
          {v.capi && <>
            <label className="grid gap-1"><span className="text-sm font-semibold">Conversions API token</span>
              <input className={inputCls} type="password" autoComplete="off" value={v.token} onChange={e => set("token", e.target.value)}
                placeholder={t?.has_capi_token ? "Saved. Paste a new one to replace it." : "From Events Manager › Settings"} />
              <span className="text-xs text-[var(--haip-fg-muted)]">Stored encrypted. HAIP never shows it again.</span></label>
            <label className="grid gap-1"><span className="text-sm font-semibold">Test event code (optional)</span>
              <input className={inputCls} value={v.test} onChange={e => set("test", e.target.value)} placeholder="TEST12345" /></label>
          </>}
          <GoogleAdsFields v={v} set={(k, val) => setF({ ...v, [k]: val })} status={t?.google_ads} />
          {t?.recent && t.recent.length > 0 && <div><p className="text-sm font-semibold">Recent events</p>
            <ul className="text-sm text-[var(--haip-fg-muted)]">{t.recent.slice(0, 8).map((e, i) => <li key={i}>{e.channel === "ga4" ? "GA4 " : e.channel === "google_ads" ? "Google Ads " : ""}{e.event_name}: {e.status}{e.reason ? ` (${e.reason})` : ""}</li>)}</ul></div>}
        </div>
      )}
    </Drawer>
  );
}
