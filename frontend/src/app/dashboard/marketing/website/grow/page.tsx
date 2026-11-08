"use client";
// Website › Grow (owner pick 8 Nov: layout A, score first): the visibility score, this week's tasks for people (checklist
// steps, drafts waiting for approval, fixes, outreach, ad suggestions), results, and the SEO agency's roles.
// Backend: GET /websites/grow, PUT /websites/seo-agency, POST /seo-agency/run, POST /seo-agency/fixes/apply.
import { useState } from "react";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardBody, CompactRow, EmptyState, PageHeader, RowList, RowTag, Stat } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn, btnPrimary } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { errorMessage } from "@/lib/bookings";
import { allowed, GROW_MANAGE_ROLES, growApi, growRow, inr, LEVEL_WORDS, LEVELS, type Grow, type Level, type Role } from "@/lib/websiteGrow";

const RING = 2 * Math.PI * 40;
const WEEK_ROWS = 6;

export default function GrowPage() {
  const { data: session } = useSession();
  const canManage = GROW_MANAGE_ROLES.includes(String(session?.user?.role ?? ""));
  const q = useQuery({ queryKey: ["web-grow"], queryFn: growApi.get, retry: false });
  const g = q.data;
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="mx-auto max-w-[1100px] space-y-5 px-4 py-5 sm:px-6">
        <PageHeader title="Grow" subtitle="How easy guests find you on Google and booking sites, and what to do this week" />
        {q.isLoading ? <Skeleton className="h-64 w-full" />
          : q.isError ? <Card><EmptyState title="Couldn't load Grow" hint={errorMessage(q.error, "Try again in a moment.")}
            action={<button className={btn} onClick={() => q.refetch()}>Try again</button>} /></Card>
          : g && (
            <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
              {/* Phones: one column in mock A's order (score, this week, results, site check, team); desktop: two columns. */}
              <div className="contents lg:grid lg:content-start lg:gap-5">
                <div className="order-1"><ScoreCard g={g} /></div>
                <div className="order-3"><Results g={g} /></div>
                {g.checker && <div className="order-4"><SiteCheck g={g} /></div>}
              </div>
              <div className="contents lg:grid lg:content-start lg:gap-5">
                <div className="order-2"><ThisWeek g={g} canManage={canManage} /></div>
                <div className="order-5"><Team g={g} canManage={canManage} /></div>
              </div>
            </div>
          )}
      </div>
    </div>
  );
}

function ScoreCard({ g }: { g: Grow }) {
  const total = g.score.total;
  return (
    <Card><CardBody className="grid gap-4">
      <div className="flex items-center gap-4">
        <svg width="96" height="96" viewBox="0 0 96 96" role="img" aria-label={`Score ${total} of 100`} className="shrink-0">
          <circle cx="48" cy="48" r="40" fill="none" strokeWidth="9" className="stroke-[var(--haip-border)]" />
          <circle cx="48" cy="48" r="40" fill="none" strokeWidth="9" strokeLinecap="round" transform="rotate(-90 48 48)"
            strokeDasharray={`${(RING * total) / 100} ${RING}`} className="stroke-[var(--primary)]" />
          <text x="48" y="54" textAnchor="middle" className="fill-[var(--haip-fg)] text-[26px] font-bold">{total}</text>
        </svg>
        <div className="grid gap-1">
          <h2 className="haip-heading text-xl font-bold">How easy you are to find</h2>
          <p className="text-sm text-[var(--haip-fg-muted)]">Out of 100, from four parts of 25.</p>
        </div>
      </div>
      <ul className="grid grid-cols-2 gap-3">
        {g.score.parts.map(p => (
          <li key={p.key} className="grid gap-1" title={p.why}>
            <span className="text-sm">{p.label}</span>
            <svg width="100%" height="6" aria-hidden="true">
              <rect width="100%" height="6" rx="3" className="fill-[var(--haip-border)]" />
              <rect width={`${(100 * p.points) / p.max}%`} height="6" rx="3" className="fill-[var(--primary)]" />
            </svg>
            <span className="text-xs text-[var(--haip-fg-muted)]">{p.points} of {p.max} · {p.why}</span>
          </li>
        ))}
      </ul>
      {g.brief?.text && (
        <div className="grid gap-1 border-t border-[var(--haip-border)] pt-3">
          <p className="text-sm font-semibold">This week on Google</p>
          <p className="text-[15px]">{g.brief.text}</p>
          {g.brief.actions.length > 0 && <ul className="list-disc pl-5 text-sm">{g.brief.actions.map(a => <li key={a}>{a}</li>)}</ul>}
        </div>
      )}
    </CardBody></Card>
  );
}

function ThisWeek({ g, canManage }: { g: Grow; canManage: boolean }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const apply = useMutation({
    mutationFn: growApi.applyFixes,
    onSuccess: d => { qc.invalidateQueries({ queryKey: ["web-grow"] });
      toast({ variant: "success", title: "Fixed", description: `${d.alt} photo description(s) now live; ${d.titles} title(s) in your draft. Publish the draft to show them.` }); },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not apply the fixes") }),
  });
  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast({ variant: "success", title: "Message copied. Send it yourself." }); }
    catch { toast({ variant: "error", title: "Couldn't copy. Select the text and copy it." }); }
  };
  const [all, setAll] = useState(false);
  const rows = g.tasks.map(growRow);
  const shown = all ? rows : rows.slice(0, WEEK_ROWS);
  return (
    <section className="grid gap-2" aria-labelledby="week">
      <div className="flex items-baseline justify-between">
        <h2 id="week" className="haip-heading text-lg font-bold">This week</h2>
        <span className="text-sm text-[var(--haip-fg-muted)]">{rows.length} to do</span>
      </div>
      {rows.length === 0 ? <Card><EmptyState title="Nothing to do this week" hint="New steps and drafts show here after Monday's run." /></Card>
        : <RowList label="This week">
          {shown.map(r => (
            <CompactRow key={r.key} href={r.copy || r.apply ? undefined : r.href} title={r.title} subtitle={r.subtitle}
              extra={<RowTag tone={r.tone}>{r.tag}</RowTag>}
              actions={r.copy ? <button className={btn} onClick={() => copy(r.copy!)}>Copy</button>
                : r.apply && canManage ? <button className={btnPrimary} disabled={apply.isPending} onClick={() => apply.mutate()}>Apply</button>
                : undefined} />
          ))}
        </RowList>}
      {rows.length > WEEK_ROWS && <button className={`${btn} justify-self-start`} onClick={() => setAll(a => !a)}>
        {all ? "Show fewer" : `Show all ${rows.length}`}</button>}
    </section>
  );
}

function Results({ g }: { g: Grow }) {
  const r = g.results;
  const shown = r.google.times_shown;
  return (
    <section className="grid gap-2" aria-labelledby="results">
      <h2 id="results" className="haip-heading text-lg font-bold">Results, last {r.days} days</h2>
      <div className="grid grid-cols-2 gap-3">
        <Stat label="Website bookings" hint={r.website ? `${r.website.bookings} booking${r.website.bookings === 1 ? "" : "s"}` : "No website yet"}
          value={!r.website ? "No data" : r.money_restricted || r.website.value === undefined ? r.website.bookings : inr(r.website.value)}
          variant={r.website?.value ? "accent" : "default"} />
        <Stat label="Shown on Google" value={shown === null ? "No data" : shown.toLocaleString("en-IN")}
          hint={shown === null ? "Connect Google on Website › Google" : "times"}
          change={r.google.change_pct === null ? null : { text: `${r.google.change_pct > 0 ? "+" : ""}${r.google.change_pct}%`,
            tone: r.google.change_pct >= 0 ? "success" : "danger" }} />
      </div>
      {!!r.ads?.spend && (
        <p className="text-sm text-[var(--haip-fg-muted)]">Meta ads: {inr(r.ads.spend)} spent, {r.ads.bookings ?? 0} bookings
          {r.ads.revenue !== undefined ? `, ${inr(r.ads.revenue)} booked` : ""} (last 30 days).</p>
      )}
    </section>
  );
}

function SiteCheck({ g }: { g: Grow }) {
  const c = g.checker;
  if (!c) return null;
  const items = [...(c.problems ?? []).map(p => `${p.title}: ${p.detail}`), ...(c.slow_pages ?? []).map(s => `${s.page} is slow on phones`),
    ...(c.sitemap && !c.sitemap.ok ? [c.sitemap.detail] : [])];
  return (
    <Card><CardBody className="grid gap-2">
      <h2 className="haip-heading text-lg font-bold">Site check</h2>
      {items.length === 0 ? <p className="text-sm text-[var(--haip-fg-muted)]">Everything the checker looks at passes.</p>
        : <ul className="grid gap-1 text-sm">{items.map(i => <li key={i}>{i}</li>)}</ul>}
      {c.applied && <p className="text-sm text-[var(--haip-fg-muted)]">Fixed on its own: {c.applied.alt} photo description(s), {c.applied.titles} title(s) in your draft.</p>}
    </CardBody></Card>
  );
}

function Team({ g, canManage }: { g: Grow; canManage: boolean }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [all, setAll] = useState(false);
  const save = useMutation({
    mutationFn: growApi.setAgency,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["web-grow"] }),
    onError: e => toast({ variant: "error", title: errorMessage(e, "Not saved") }),
  });
  const run = useMutation({
    mutationFn: growApi.run,
    onSuccess: () => toast({ variant: "success", title: "The SEO team is running. New tasks show here in a few minutes." }),
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not start the run") }),
  });
  const paused = g.settings.paused;
  const roles = all ? g.roster : g.roster.slice(0, 3);
  return (
    <section className="grid gap-2" aria-labelledby="team">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="team" className="haip-heading text-lg font-bold">Your SEO team</h2>
        <span className="text-sm text-[var(--haip-fg-muted)]">
          {paused ? "Paused" : g.last_run?.at ? `Last ran ${new Date(g.last_run.at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", hour: "numeric", minute: "2-digit" })}` : "Runs every Monday from 09:00"}
        </span>
      </div>
      <Card><CardBody className="grid gap-3">
        <ul className="grid gap-3">
          {roles.map(r => <RoleRow key={r.role} r={r} canManage={canManage && !paused} busy={save.isPending}
            onPick={lvl => save.mutate({ roles: { [r.role]: lvl } })} />)}
        </ul>
        <div className="flex flex-wrap items-center gap-2 border-t border-[var(--haip-border)] pt-3">
          <button className={`${btn} mr-auto`} onClick={() => setAll(a => !a)}>{all ? "Show fewer" : `See all ${g.roster.length} roles`}</button>
          {canManage && <>
            <button className={btn} disabled={paused || run.isPending} onClick={() => run.mutate()}>Run now</button>
            <button className={paused ? btnPrimary : btn} disabled={save.isPending} onClick={() => save.mutate({ paused: !paused })}>
              {paused ? "Switch back on" : "Pause all"}</button>
          </>}
        </div>
        <p className="text-xs text-[var(--haip-fg-muted)]">The team never posts, logs in or pays on Google, Airbnb or any other site. A person does those steps.</p>
      </CardBody></Card>
    </section>
  );
}

function RoleRow({ r, canManage, busy, onPick }: { r: Role; canManage: boolean; busy: boolean; onPick: (l: Level) => void }) {
  return (
    <li className="grid gap-2">
      <div className="grid gap-0.5"><span className="font-semibold">{r.label}</span><span className="text-sm text-[var(--haip-fg-muted)]">{r.does}</span></div>
      {canManage ? (
        <div role="radiogroup" aria-label={`${r.label} level`} className="flex flex-wrap gap-1.5">
          {LEVELS.filter(l => allowed(l, r.max_level)).map(l => (
            <button key={l} role="radio" aria-checked={r.level === l} disabled={busy} onClick={() => r.level !== l && onPick(l)}
              className={`min-h-11 rounded-full border px-3.5 text-sm font-semibold ${r.level === l
                ? "border-primary bg-primary text-white" : "border-[var(--haip-border)] bg-[var(--haip-surface)]"}`}>
              {LEVEL_WORDS[l]}</button>
          ))}
        </div>
      ) : <RowTag tone={r.effective_level === "off" ? "neutral" : "brand"}>{LEVEL_WORDS[r.effective_level]}</RowTag>}
    </li>
  );
}
