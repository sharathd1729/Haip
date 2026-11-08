"use client";
// Google connections for the website: Search Console (connect, property, searches to follow, disconnect), the Business
// Profile (the Marketing Studio connection, read here for its metrics) and PageSpeed. Used on Website › Google and on
// Settings › Integrations. Backend: endpoints/website_google.py. Owner/manager change things; others only read.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe } from "lucide-react";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls, openOAuth } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webError } from "@/lib/website";
import { googleApi, type Pull } from "@/lib/websiteGoogle";

function PullLine({ pull }: { pull: Pull }) {
  if (pull.failures) return <p className="text-sm text-[var(--haip-status-warning-fg)]">{pull.last_error}</p>;
  if (pull.last_ok_at) return <p className="text-xs text-[var(--haip-fg-muted)]">Last read {new Date(pull.last_ok_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</p>;
  return null;
}

export function GoogleConnections({ canManage, hideOnError = false }: { canManage: boolean; hideOnError?: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery({ queryKey: ["web-google"], queryFn: () => googleApi.overview(), retry: hideOnError ? false : 3 });
  const [draft, setDraft] = useState<string | null>(null);
  const done = (title: string) => () => { qc.invalidateQueries({ queryKey: ["web-google"] }); qc.invalidateQueries({ queryKey: ["web-report"] }); toast({ variant: "success", title }); };
  const fail = (e: unknown) => toast({ variant: "error", title: "Not saved", description: webError(e, "Try again.") });
  const prop = useMutation({ mutationFn: googleApi.property, onSuccess: done("Property saved"), onError: fail });
  const money = useMutation({ mutationFn: googleApi.moneyQueries, onSuccess: () => { setDraft(null); done("Searches saved")(); }, onError: fail });
  const off = useMutation({ mutationFn: googleApi.disconnect, onSuccess: done("Search Console disconnected. Its data was deleted."), onError: fail });

  if (q.isLoading) return <Card><CardBody><div className="h-40 animate-pulse rounded-xl bg-[var(--haip-border)]" /></CardBody></Card>;
  if (q.isError && hideOnError) return null;     // e.g. the website module is off for this workspace
  if (q.isError || !q.data) return <Card><CardBody><p className="text-sm">Couldn&apos;t load your Google connections. <button className="underline" onClick={() => q.refetch()}>Try again</button></p></CardBody></Card>;
  const { search_console: sc, business_profile: bp, pagespeed } = q.data;
  const text = draft ?? sc.money_queries.join("\n");
  return (
    <Card>
      <CardHeader icon={Globe} title="Google" description="What Google says about your business and website" />
      <CardBody className="grid gap-5 text-[15px]">
        <section className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <b className="mr-auto font-semibold">Search Console</b>
            {sc.connected ? <StatusPill tone="success">Connected</StatusPill> : <StatusPill tone="neutral">Not connected</StatusPill>}
          </div>
          <p className="text-sm text-[var(--haip-fg-muted)]">How often your website shows in Google search, for which searches, and your position.</p>
          {!sc.connected && (sc.available
            ? canManage && <button type="button" className={`${btnPrimary} w-full sm:w-auto`} onClick={() => openOAuth("/websites/google/search-console/oauth-start")}>Connect Search Console</button>
            : <p className="text-sm">Google sign-in is not set up on this HAIP server yet.</p>)}
          {sc.connected && <>
            <label className="grid gap-1"><span className="text-sm font-semibold">Property</span>
              <select className={inputCls} value={sc.property ?? ""} disabled={!canManage || prop.isPending} onChange={e => e.target.value && prop.mutate(e.target.value)}>
                <option value="">Choose your website&apos;s property</option>
                {sc.properties.map(p => <option key={p.site_url} value={p.site_url}>{p.site_url.startsWith("sc-domain:") ? `${p.site_url.slice(10)} (whole domain)` : p.site_url}</option>)}
              </select></label>
            {!sc.property && <p className="text-sm text-[var(--haip-status-warning-fg)]">None of these is your website&apos;s address. Add it in Search Console, or pick the right one.</p>}
            {sc.sitemap_submitted && <p className="text-xs text-[var(--haip-fg-muted)]">Sitemap sent to Google: {sc.sitemap_submitted}</p>}
            {sc.sitemap_problem && <p className="text-sm text-[var(--haip-status-warning-fg)]">{sc.sitemap_problem}</p>}
            <PullLine pull={sc.pull} />
            <label className="grid gap-1"><span className="text-sm font-semibold">Searches that bring bookings (one per line, up to 10)</span>
              <textarea className={`${inputCls} min-h-24`} value={text} disabled={!canManage} onChange={e => setDraft(e.target.value)} placeholder={"villa in coorg\npool villa near bangalore"} /></label>
            {canManage && <div className="flex flex-wrap gap-2">
              <button className={btnPrimary} disabled={draft == null || money.isPending} onClick={() => money.mutate(text.split("\n").map(s => s.trim()).filter(Boolean))}>{money.isPending ? "Saving…" : "Save searches"}</button>
              <button className={btn} disabled={off.isPending} onClick={() => { if (window.confirm("Disconnect Search Console? HAIP deletes the search data it read.")) off.mutate(); }}>Disconnect</button>
            </div>}
          </>}
        </section>
        <section className="grid gap-2 border-t border-[var(--haip-border)] pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <b className="mr-auto font-semibold">Business Profile</b>
            {bp.connected ? <StatusPill tone="success">Connected</StatusPill> : <StatusPill tone="neutral">Not connected</StatusPill>}
          </div>
          <p className="text-sm text-[var(--haip-fg-muted)]">Views on Search and Maps, calls, directions, website clicks and messages{bp.connected ? `, for ${bp.locations} location${bp.locations === 1 ? "" : "s"}` : ""}. Same connection Marketing Studio uses for reviews.</p>
          {!bp.connected && bp.available && canManage && <button type="button" className={`${btn} w-full sm:w-auto`} onClick={() => openOAuth("/marketing/studio/channels/google/oauth-start")}>Connect Business Profile</button>}
          {!bp.connected && !bp.available && <p className="text-sm">Google sign-in is not set up on this HAIP server yet.</p>}
          {bp.connected && <PullLine pull={bp.pull} />}
        </section>
        <section className="grid gap-1 border-t border-[var(--haip-border)] pt-4">
          <b className="font-semibold">Speed check</b>
          <p className="text-sm text-[var(--haip-fg-muted)]">{pagespeed.configured ? "Google PageSpeed measures your home page and top stay pages every Monday." : "Google PageSpeed is not set up on this HAIP server yet (PAGESPEED_API_KEY), so real-visitor speed is not measured."}</p>
        </section>
      </CardBody>
    </Card>
  );
}
