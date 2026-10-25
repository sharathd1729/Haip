"use client";
// Website overview (Marketing › Website): pages, the publish checklist, versions and approvals, look and feel,
// booking settings, domains and results. The editor opens from here.
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardBody, CardHeader, DataTable, EmptyState, Stat, StatusPill, type Tone } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webApi, webError, type SiteOut, type SiteSettings, type VersionRow } from "@/lib/website";
import { SPEC, type Page } from "@/site-blocks/types";
import { ThemePicker } from "./PagePanel";
import { useDraft } from "./useDraft";

const VERSION_TONE: Record<string, Tone> = { draft: "warning", in_review: "info", published: "success", superseded: "neutral", rejected: "danger", withdrawn: "neutral", approved: "success" };
const MODE: Record<SiteSettings["booking_mode"], [string, string]> = {
  request: ["Request to book", "Guests send dates; your team confirms and sends a payment link."],
  instant: ["Instant booking", "Guests pay in full on the site; the booking is confirmed at once."],
  deposit: ["Deposit now, balance later", "Guests pay a part now; the rest by payment link before arrival."],
  enquiry: ["Enquiries only", "No booking form; guests send an enquiry that lands in Leads."],
};

// A new-builder (v2) draft names pages by slug instead of id/path.
const slugOf = (p: Page) => (p as unknown as { slug?: string }).slug || "";

function seoReady(p: Page) { return p.seo.title.length > 0 && p.seo.description.length >= 50 && p.seo.description.length <= 160; }

export function Overview({ site, role }: { site: SiteOut; role: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const draft = useDraft();
  const canApprove = role === "owner" || role === "manager";
  const versions = useQuery({ queryKey: ["web-versions"], queryFn: webApi.versions });
  const analytics = useQuery({ queryKey: ["web-analytics"], queryFn: () => webApi.analytics(30) });
  const done = (s: SiteOut, title: string) => { qc.setQueryData(["web-site"], s); qc.invalidateQueries({ queryKey: ["web-versions"] }); draft.load(); toast({ variant: "success", title }); };
  const fail = (title: string) => (e: unknown) => toast({ variant: "error", title, description: webError(e, "Try again.") });
  const publish = useMutation({ mutationFn: (id: string) => webApi.publish(id), onSuccess: s => done(s, "Published"), onError: fail("Not published") });
  const reject = useMutation({ mutationFn: (id: string) => webApi.reject(id, window.prompt("What should change? (optional)") || undefined), onSuccess: s => done(s, "Sent back"), onError: fail("Not sent back") });
  const submit = useMutation({ mutationFn: (id: string) => webApi.submit(id), onSuccess: s => done(s, "Sent for approval"), onError: fail("Not sent") });
  const restore = useMutation({ mutationFn: (id: string) => webApi.restore(id), onSuccess: () => { draft.load(); qc.invalidateQueries({ queryKey: ["web-versions"] }); toast({ variant: "success", title: "Restored as a new draft" }); }, onError: fail("Not restored") });
  const pause = useMutation({ mutationFn: (on: boolean) => webApi.pause(on), onSuccess: s => done(s, s.status === "paused" ? "Website paused" : "Website back online"), onError: fail("Not changed") });

  const doc = draft.doc;
  // A new-builder (v2) draft has `tokens`, not the classic `theme`; the classic theme picker and page editor can't open it.
  const isV2 = (doc as unknown as { spec_version?: number } | null)?.spec_version === 2;
  const blocking = draft.checks.filter(c => c.level === "block");
  const v = draft.version;
  const host = site.url.replace("https://", "");
  const next = site.live ? null
    : !v ? "Create a first version with the art director."
    : blocking.length ? `Fix ${blocking.length} ${blocking.length === 1 ? "item" : "items"} under "Ready to publish?", then publish v${v.number}.`
    : role === "owner" ? `Publish v${v.number} below.` : canApprove ? `Publish v${v.number} below, or send it to the owner.` : `Send v${v.number} for approval below.`;
  return (
    <div className="grid gap-4">
      <Card>
        <CardBody className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <StatusPill tone={site.status === "live" ? "success" : site.status === "paused" ? "neutral" : "warning"}>
            {site.status === "live" ? "Live" : site.status === "paused" ? "Paused" : "Not live yet"}</StatusPill>
          <p className="min-w-0 flex-1 text-sm">
            {site.live ? <>Guests see v{site.live.number} at <a className="font-semibold underline underline-offset-4" href={site.url} target="_blank" rel="noopener noreferrer">{host}</a>.</>
              : <>Nobody can see the site yet. Once published it opens at <b className="font-semibold">{host}</b>.</>}
            {next && <span className="block text-[var(--haip-fg-muted)]">Next: {next}</span>}
          </p>
        </CardBody>
      </Card>
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="grid content-start gap-4">
        <Card>
          <CardHeader title="Pages" description={`${doc?.pages.length ?? 0} pages · stay pages are filled from Properties`}
            actions={<>{(role === "owner" || role === "manager") && <Link className={btn} href="/dashboard/marketing/website/builder">Design with the art director</Link>}
              <Link className={btnPrimary} href="/dashboard/marketing/website/edit">Open editor</Link></>} />
          <CardBody>
            {!doc ? <p className="text-sm text-[var(--haip-fg-muted)]">Loading…</p> : (
              <DataTable rows={doc.pages} rowKey={p => p.id || slugOf(p)} columns={[
                { key: "t", header: "Page", cell: p => <div><b>{p.title}</b><div className="text-xs text-[var(--haip-fg-subtle)]">{p.path || slugOf(p)}</div></div> },
                { key: "k", header: "Type", hideBelow: "sm", cell: p => SPEC.system_pages[p.key]?.system ? <StatusPill tone="neutral">Built by HAIP</StatusPill>
                  : p.key === "stay" ? <StatusPill tone="info">Template</StatusPill> : SPEC.system_pages[p.key]?.required ? <StatusPill tone="neutral">Required</StatusPill> : <StatusPill tone="success">Page</StatusPill> },
                { key: "s", header: "Search preview", cell: p => (["stay", "book", "manage"].includes(p.key) ? <span className="text-xs text-[var(--haip-fg-subtle)]">Automatic</span>
                  : seoReady(p) ? <StatusPill tone="success">Ready</StatusPill> : <StatusPill tone="warning">Needs a description</StatusPill>) },
                { key: "e", header: "", align: "right", cell: p => <Link className={btn} href={isV2 ? "/dashboard/marketing/website/builder" : `/dashboard/marketing/website/edit?page=${p.id}`}>Edit</Link> },
              ]} />
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Versions" description="An approval belongs to one version. Editing after sending makes a new version and withdraws the request." />
          <CardBody>
            <DataTable rows={versions.data || []} rowKey={(r: VersionRow) => r.id} loading={versions.isLoading} error={versions.isError ? "Couldn't load versions." : null}
              onRetry={() => versions.refetch()} empty={{ title: "No versions yet" }} columns={[
                { key: "n", header: "Version", cell: r => <b>v{r.number}</b> },
                { key: "s", header: "Status", cell: r => <StatusPill tone={VERSION_TONE[r.status] || "neutral"}>{r.status.replace("_", " ")}</StatusPill> },
                { key: "o", header: "Made by", hideBelow: "md", cell: r => <span className="text-sm">{r.note?.startsWith("Art director") ? "Art director" : r.origin === "ai" ? "AI developer" : r.origin === "seed" ? "HAIP (first draft)" : r.origin === "restore" ? "Restore" : "Team"}{r.note ? <span className="block text-xs text-[var(--haip-fg-subtle)]">{r.note.replace(/^Art director: /, "Look: ")}</span> : null}</span> },
                { key: "a", header: "", align: "right", cell: r => (
                  <div className="flex justify-end gap-1.5">
                    {r.status === "in_review" && canApprove && <><button className={btnPrimary} onClick={() => publish.mutate(r.id)} disabled={publish.isPending}>Approve &amp; publish</button>
                      <button className={btn} onClick={() => reject.mutate(r.id)}>Send back</button></>}
                    {r.status === "draft" && r.id === v?.id && blocking.length > 0 && <span className="self-center text-xs text-[var(--haip-fg-muted)]">Fix {blocking.length} first</span>}
                    {r.status === "draft" && r.id === v?.id && (role === "owner" ? <button className={btnPrimary} onClick={() => publish.mutate(r.id)} disabled={publish.isPending || blocking.length > 0}>Publish</button>
                      : <button className={btn} onClick={() => submit.mutate(r.id)} disabled={blocking.length > 0}>Send for approval</button>)}
                    {["superseded", "rejected", "withdrawn"].includes(r.status) && <button className={btn} onClick={() => restore.mutate(r.id)}>Restore</button>}
                  </div>) },
              ]} />
          </CardBody>
        </Card>
        <Results analytics={analytics.data} loading={analytics.isLoading} error={analytics.isError} />
      </div>
      <div className="grid content-start gap-4">
        <Card>
          <CardHeader title="Ready to publish?" actions={blocking.length ? <StatusPill tone="warning">{blocking.length} to fix</StatusPill> : <StatusPill tone="success">Ready</StatusPill>} />
          <CardBody>
            <ul className="grid gap-2.5">
              {draft.checks.map(c => (
                <li key={c.key} className="grid grid-cols-[auto_1fr] gap-2.5 text-sm">
                  <span aria-hidden="true" className={`mt-1.5 h-2.5 w-2.5 rounded-full ${c.ok ? "bg-[var(--haip-status-success-fg)]" : c.level === "block" ? "bg-[var(--haip-status-danger-fg)]" : "bg-[var(--haip-status-warning-fg)]"}`} />
                  <span><b className="font-semibold">{c.title}</b>{!c.ok && <span className="sr-only">{c.level === "block" ? " (blocks publishing)" : " (warning)"}</span>}<span className="block text-[13px] text-[var(--haip-fg-muted)]">{c.detail}</span></span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Look and feel" description={isV2 ? "Set by the look you picked with the art director." : "A regional theme pack sets colours, fonts and the border pattern; personality sets shape and tone."} />
          <CardBody>{!doc ? null : isV2
            ? <Link className={btn} href="/dashboard/marketing/website/builder">Change the look with the art director</Link>
            : <ThemePicker doc={doc} update={draft.update} />}</CardBody>
        </Card>
        <BookingSettings site={site} canEdit={canApprove} isV2={isV2} />
        <Domains site={site} canEdit={canApprove} />
        {canApprove && site.live && <Card><CardBody className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm">{site.status === "paused" ? "The website is paused: visitors see a not-available page." : "Need to take the site offline for a while?"}</span>
          <button className={btn} onClick={() => pause.mutate(site.status !== "paused")}>{site.status === "paused" ? "Bring back online" : "Pause website"}</button></CardBody></Card>}
      </div>
    </div>
    </div>
  );
}

function Results({ analytics, loading, error }: { analytics?: import("@/lib/website").Analytics; loading: boolean; error: boolean }) {
  const b = analytics?.bookings || {};
  return (
    <Card>
      <CardHeader title="Results" description="Last 30 days" />
      <CardBody>
        {error ? <p className="text-sm">Couldn&apos;t load results.</p> : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Page views" value={analytics?.views.total ?? "–"} loading={loading} />
            <Stat label="Website leads" value={analytics?.website_leads ?? "–"} loading={loading} />
            <Stat label="Bookings paid" value={b.confirmed?.count ?? 0} hint={b.confirmed?.value ? `₹${Math.round(Number(b.confirmed.value)).toLocaleString("en-IN")}` : undefined} loading={loading} />
            <Stat label="Requests" value={b.requested?.count ?? 0} loading={loading} />
          </div>
        )}
        {analytics && analytics.views.sources.length > 0 && <p className="mt-3 text-[13px] text-[var(--haip-fg-muted)]">Top sources: {analytics.views.sources.slice(0, 4).map(([s, n]) => `${s} (${n})`).join(", ")}</p>}
      </CardBody>
    </Card>
  );
}

// The new builder (v2) can't take payments until it has a policies page, and shows prices by the workspace price rule.
const V2_LOCKED: SiteSettings["booking_mode"][] = ["instant", "deposit"];

function BookingSettings({ site, canEdit, isV2 }: { site: SiteOut; canEdit: boolean; isV2: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [s, setS] = useState<SiteSettings>(site.settings);
  const save = useMutation({ mutationFn: () => webApi.settings(s), onSuccess: out => { qc.setQueryData(["web-site"], out); toast({ variant: "success", title: "Booking settings saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: webError(e, "Try again.") }) });
  const changed = JSON.stringify(s) !== JSON.stringify(site.settings);
  return (
    <Card>
      <CardHeader title="Booking on the website" description="Prices and free dates always come from Bookings and Rate plans." />
      <CardBody className="grid gap-3">
        <fieldset className="grid gap-2" disabled={!canEdit}>
          <legend className="sr-only">Booking mode</legend>
          {(Object.keys(MODE) as SiteSettings["booking_mode"][]).map(k => {
            const locked = isV2 && V2_LOCKED.includes(k);
            return (
              <label key={k} className={`grid grid-cols-[auto_1fr] gap-2.5 rounded-xl border p-3 ${locked ? "cursor-not-allowed opacity-60" : "cursor-pointer"} ${s.booking_mode === k ? "border-[var(--primary)] bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)]"}`}>
                <input type="radio" name="mode" className="mt-1 h-4 w-4 accent-[var(--primary)]" checked={s.booking_mode === k} disabled={locked} onChange={() => setS({ ...s, booking_mode: k })} />
                <span><b className="text-sm">{MODE[k][0]}</b><span className="block text-[13px] text-[var(--haip-fg-muted)]">{locked ? "Not available yet on the new builder: it needs the policies page, coming soon." : MODE[k][1]}</span></span>
              </label>
            );
          })}
          {s.booking_mode === "deposit" && <label className="grid gap-1"><span className="text-[13px] font-semibold">Deposit (% of the total)</span>
            <input type="number" min={10} max={100} className={inputCls} value={s.deposit_percent} onChange={e => setS({ ...s, deposit_percent: Number(e.target.value) })} /></label>}
          {isV2 ? <p className="text-[13px] text-[var(--haip-fg-muted)]">Prices follow your workspace price rule. If the AI may not quote prices, the site shows &ldquo;Get the price on WhatsApp&rdquo; instead of a figure.</p>
            : <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={s.show_prices} onChange={e => setS({ ...s, show_prices: e.target.checked })} />Show prices on the site</label>}
          <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={s.prices_include_gst} onChange={e => setS({ ...s, prices_include_gst: e.target.checked })} />My rates already include GST</label>
        </fieldset>
        {canEdit && <button className={btnPrimary} disabled={!changed || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save booking settings"}</button>}
      </CardBody>
    </Card>
  );
}

function Domains({ site, canEdit }: { site: SiteOut; canEdit: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [host, setHost] = useState("");
  const set = (s: SiteOut) => qc.setQueryData(["web-site"], s);
  const add = useMutation({ mutationFn: () => webApi.addDomain(host), onSuccess: s => { set(s); setHost(""); }, onError: e => toast({ variant: "error", title: "Not added", description: webError(e, "Check the domain.") }) });
  const verify = useMutation({ mutationFn: (id: string) => webApi.verifyDomain(id), onSuccess: set, onError: e => toast({ variant: "error", title: "Couldn't check", description: webError(e, "Try again.") }) });
  const remove = useMutation({ mutationFn: (id: string) => webApi.removeDomain(id), onSuccess: set });
  return (
    <Card>
      <CardHeader title="Web address" description="Your free HAIP address works at once. Add your own domain any time." />
      <CardBody className="grid gap-3">
        {site.domains.map(d => (
          <div key={d.id} className="grid gap-1.5 rounded-xl border border-[var(--haip-border)] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <a className="font-semibold underline-offset-2 hover:underline" href={`https://${d.hostname}`} target="_blank" rel="noopener noreferrer">{d.hostname}</a>
              <StatusPill tone={d.status === "active" ? "success" : d.status === "verified" ? "info" : "warning"}>{d.kind === "subdomain" ? "Free address" : d.status}</StatusPill>
            </div>
            {d.kind === "custom" && d.status !== "active" && (
              <div className="grid gap-1 text-[13px]">
                <p>Add these at your domain provider, then check:</p>
                <code className="block overflow-x-auto rounded-lg bg-[var(--haip-surface)] p-2 text-xs">TXT  _haip-verify.{d.hostname}  {d.verify_token}{"\n"}CNAME  {d.hostname}  {d.cname_target}</code>
                {d.error && <p className="text-[var(--haip-status-warning-fg)]">{d.error}</p>}
              </div>
            )}
            {d.kind === "custom" && canEdit && <div className="flex gap-1.5">
              {d.status !== "active" && <button className={btn} onClick={() => verify.mutate(d.id)} disabled={verify.isPending}>Check DNS</button>}
              <button className={btn} onClick={() => remove.mutate(d.id)}>Remove</button></div>}
          </div>
        ))}
        {canEdit && <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (host.trim()) add.mutate(); }}>
          <input className={inputCls} placeholder="www.yourvilla.in" value={host} onChange={e => setHost(e.target.value)} aria-label="Your domain" />
          <button className={btn} type="submit" disabled={add.isPending}>Add domain</button></form>}
      </CardBody>
    </Card>
  );
}

export function NoSite({ canCreate }: { canCreate: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const create = useMutation({ mutationFn: webApi.create, onSuccess: s => { qc.setQueryData(["web-site"], s); toast({ variant: "success", title: "Your website draft is ready" }); },
    onError: e => toast({ variant: "error", title: "Couldn't create the website", description: webError(e, "Try again.") }) });
  return (
    <Card><EmptyState title="Create your website"
      hint="HAIP builds a complete first draft from your business details and properties: home, stays, a stay page for each property, booking, contact and policies. Nothing goes live until it's published."
      action={canCreate ? <button className={btnPrimary} disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? "Building…" : "Create my website"}</button>
        : <span className="text-sm">Ask an owner or manager to create it.</span>} /></Card>
  );
}
