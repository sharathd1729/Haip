"use client";
// The strategist (studio plan phase 3): theme radar (scored in code), shoot & collab briefs, monthly deck, season calendar.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, EmptyState, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, day, inputCls, studioError, when } from "./types";

interface Theme { theme: string; kind: string; dates: { from: string; to: string } | null; score: number; shoot_by: string;
  evidence: { kind: "own" | "platform" | "google"; text: string }[] }
interface Shot { n: number; use: string; scene: string; shot_size: string; angle: string; movement: string; lens: string;
  duration_s: number; time_of_day: string; talent: string[]; props: string[]; on_screen_text: string; why: string; priority: string }
interface Brief { focus: string; must_get: string[]; shots: Shot[]; broll: string[]; hooks: { text: string; type: string }[];
  reels: { title: string; shots: number[]; length_s: number; cta: string }[]; captions: string[];
  posting_plan: { week: number; kind: string; what: string }[];
  collab: { creator_brief: string; deliverables: string[]; usage_rights: string; asci_label: string; tracking_code: string } | null }
interface Doc { id: string; title: string; status: "pending" | "ready" | "failed"; error: string | null; created_at: string;
  body: Record<string, unknown> | null; facts: { tracking?: { code: string; whatsapp: string | null } } | null }
interface CalEntry { name: string; start: string; end: string; keywords: string[] }

const EV: Record<string, Tone> = { own: "success", platform: "info", google: "highlight" };
const ST: Record<Doc["status"], Tone> = { pending: "info", ready: "success", failed: "danger" };

function BriefView({ b, tracking }: { b: Brief; tracking?: { code: string; whatsapp: string | null } }) {
  return (
    <div className="space-y-3 text-sm">
      <p className="font-semibold">{b.focus}</p>
      <p><b>Must get:</b> {b.must_get.join(" · ")}</p>
      <ol className="space-y-1">
        {b.shots.map(s => (
          <li key={s.n} className="rounded-lg bg-[var(--haip-surface)] p-2">
            <b>{s.n}. {s.scene}</b> <StatusPill tone={s.priority === "must" ? "warning" : "neutral"} className="ml-1">{s.priority}</StatusPill>
            <p className="text-xs text-[var(--haip-fg-muted)]">{s.use} · {s.shot_size} · {s.angle} · {s.movement} · {s.lens} · {s.duration_s}s · {s.time_of_day}{s.talent.length ? ` · ${s.talent.join(", ")}` : ""}{s.props.length ? ` · props: ${s.props.join(", ")}` : ""}{s.on_screen_text ? ` · text: “${s.on_screen_text}”` : ""}</p>
            <p className="text-xs text-[var(--haip-fg-subtle)]">Why: {s.why}</p>
          </li>
        ))}
      </ol>
      {!!b.broll.length && <p><b>B-roll:</b> {b.broll.join(" · ")}</p>}
      <p><b>Hooks:</b> {b.hooks.map(h => `“${h.text}” (${h.type})`).join(" · ")}</p>
      <p><b>Reels:</b> {b.reels.map(r => `${r.title}: shots ${r.shots.join(", ")}, ${r.length_s}s, ${r.cta}`).join(" · ")}</p>
      <p><b>Captions:</b> {b.captions.join(" / ")}</p>
      <p><b>Posting plan:</b> {b.posting_plan.map(p => `week ${p.week} ${p.kind}: ${p.what}`).join(" · ")}</p>
      {tracking && <p className="text-xs text-[var(--haip-fg-muted)]">WhatsApp tracking code: <span className="font-mono">{tracking.code}</span></p>}
      {b.collab && (
        <div className="rounded-lg border border-[var(--haip-border)] p-2">
          <p><b>Collab</b> <StatusPill tone="warning" className="ml-1">Label: {b.collab.asci_label}</StatusPill></p>
          <p>{b.collab.creator_brief}</p>
          <p className="text-xs">Deliverables: {b.collab.deliverables.join(", ")} · Usage rights: {b.collab.usage_rights} · Code {b.collab.tracking_code}</p>
        </div>
      )}
    </div>
  );
}

export function StrategyTab() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canApprove = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [form, setForm] = useState<{ theme: string; date: string; vehicle: string; route: string; people: string; collab: boolean; creator: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const radar = useQuery<{ top: Theme[] }>({ queryKey: ["studio-radar"], queryFn: () => api.get(`${STUDIO}/radar`).then(r => r.data) });
  const briefs = useQuery<Doc[]>({ queryKey: ["studio-briefs"], queryFn: () => api.get(`${STUDIO}/briefs`).then(r => r.data),
    refetchInterval: d => (d.state.data?.some(b => b.status === "pending") ? 5000 : false) });
  const deck = useQuery<{ deck: Doc | null }>({ queryKey: ["studio-deck"], enabled: canApprove, queryFn: () => api.get(`${STUDIO}/decks/latest`).then(r => r.data),
    refetchInterval: d => (d.state.data?.deck?.status === "pending" ? 5000 : false) });
  const cal = useQuery<{ entries: CalEntry[] }>({ queryKey: ["studio-calendar"], queryFn: () => api.get(`${STUDIO}/calendar`).then(r => r.data) });
  const ask = useMutation({
    mutationFn: () => api.post(`${STUDIO}/briefs`, form),
    onSuccess: () => { setForm(null); qc.invalidateQueries({ queryKey: ["studio-briefs"] }); toast({ variant: "success", title: "Writing the brief" }); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });
  const produce = useMutation({
    mutationFn: (id: string) => api.post(`${STUDIO}/briefs/${id}/produce`),
    onSuccess: r => { qc.invalidateQueries({ queryKey: ["studio-briefs"] });
      toast({ variant: "success", title: `${r.data.items.length} drafts made`, description: "Reels (one as a trial Reel), a carousel and a story, under Create > Content." }); },
    onError: e => toast({ variant: "error", title: "No drafts made", description: studioError(e, "Try again.") }),
  });
  const runDeck = useMutation({ mutationFn: () => api.post(`${STUDIO}/decks/run`), onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-deck"] }),
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }) });
  const d = deck.data?.deck?.body as Record<string, string | string[]> | undefined;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Theme radar" description="Top themes for the next 4-8 weeks, scored 0-100 from season, your leads, Google, platforms, past posts, competitor gaps, free vehicles and novelty." />
        <CardBody>
          {radar.isLoading ? <Skeleton className="h-24 w-full" /> : radar.isError ? <EmptyState title="Could not load the radar" hint={studioError(radar.error, "Try again.")} />
            : !radar.data?.top.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No themes in the next 8 weeks. Add dates to the season calendar below.</p> : (
            <ul className="space-y-2">
              {radar.data.top.map(t => (
                <li key={t.theme} className="rounded-xl border border-[var(--haip-border)] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-semibold">{t.theme} <span className="text-xs font-normal text-[var(--haip-fg-subtle)]">{t.dates ? `${day(t.dates.from)} – ${day(t.dates.to)}` : "any time"}</span></p>
                    <span className="flex items-center gap-2"><StatusPill tone="highlight">{t.score}/100</StatusPill>
                      <button type="button" className={btn} onClick={() => setForm({ theme: t.theme, date: "", vehicle: "", route: "", people: "", collab: false, creator: "" })}>Write a shoot brief</button></span>
                  </div>
                  <p className="text-xs text-[var(--haip-fg-muted)]">Shoot by {day(t.shoot_by)}</p>
                  <p className="mt-1 flex flex-wrap gap-1">{t.evidence.map((e, i) => <StatusPill key={i} tone={EV[e.kind]}>{e.kind}: {e.text}</StatusPill>)}</p>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {form && (
        <Card className="p-4">
          <form className="grid gap-2 sm:grid-cols-2" onSubmit={e => { e.preventDefault(); ask.mutate(); }}>
            <p className="font-semibold sm:col-span-2">Shoot brief: {form.theme}</p>
            <input className={inputCls} type="date" aria-label="Shoot date" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} />
            <input className={inputCls} placeholder="Vehicle (e.g. Ratha 1)" value={form.vehicle} onChange={e => setForm({ ...form, vehicle: e.target.value })} />
            <input className={inputCls} placeholder="Route or location" value={form.route} onChange={e => setForm({ ...form, route: e.target.value })} />
            <input className={inputCls} placeholder="Who is coming (couple, family...)" value={form.people} onChange={e => setForm({ ...form, people: e.target.value })} />
            <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="h-5 w-5" checked={form.collab} onChange={e => setForm({ ...form, collab: e.target.checked })} /> With a creator</label>
            {form.collab && <input className={inputCls} placeholder="@creator" value={form.creator} onChange={e => setForm({ ...form, creator: e.target.value })} />}
            <span className="flex gap-2 sm:col-span-2"><button type="submit" className={btnPrimary} disabled={ask.isPending}>Write the brief</button><button type="button" className={btn} onClick={() => setForm(null)}>Cancel</button></span>
          </form>
        </Card>
      )}

      <Card>
        <CardHeader title="Shoot & collab briefs" description="Shot list, hooks, Reel scripts, captions and a posting plan. Collabs get the ASCI label and a tracking code." />
        <CardBody>
          {briefs.isLoading ? <Skeleton className="h-16 w-full" /> : briefs.isError ? <p className="text-sm text-[var(--haip-status-danger-fg)]">{studioError(briefs.error, "Could not load briefs.")}</p>
            : !briefs.data?.length ? <p className="text-sm text-[var(--haip-fg-subtle)]">No briefs yet. Pick a theme above.</p> : (
            <ul className="space-y-2">
              {briefs.data.map(b => (
                <li key={b.id} className="rounded-xl border border-[var(--haip-border)] p-3">
                  <button type="button" className="flex w-full min-h-11 items-center justify-between gap-2 text-left" onClick={() => setOpen(open === b.id ? null : b.id)}>
                    <span className="font-semibold">{b.title}</span>
                    <span className="text-xs text-[var(--haip-fg-subtle)]">{when(b.created_at)} <StatusPill tone={ST[b.status]} className="ml-1">{b.status}</StatusPill></span>
                  </button>
                  {b.error && <p className="text-xs text-[var(--haip-status-danger-fg)]">{b.error}</p>}
                  {open === b.id && b.body && <BriefView b={b.body as unknown as Brief} tracking={b.facts?.tracking} />}
                  {open === b.id && b.status === "ready" && (
                    <button type="button" className={`${btn} mt-2`} disabled={produce.isPending} onClick={() => produce.mutate(b.id)}>Make drafts from this brief</button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {canApprove && (
        <Card>
          <CardHeader title="Monthly strategy deck" description="Written on the 1st: last month vs goal, learnings, market notes, themes, shoot plan, hooks, collabs, ad concepts."
            actions={<button type="button" className={btn} disabled={runDeck.isPending} onClick={() => runDeck.mutate()}>Write this month's</button>} />
          <CardBody className="space-y-2 text-sm">
            {deck.isLoading ? <Skeleton className="h-16 w-full" /> : !deck.data?.deck ? <p className="text-[var(--haip-fg-subtle)]">No deck yet.</p>
              : deck.data.deck.status !== "ready" || !d ? <StatusPill tone={ST[deck.data.deck.status]}>{deck.data.deck.status}</StatusPill> : (
              <>
                <p className="font-semibold">{d.headline as string}</p>
                <p>{d.last_month as string}</p>
                {(["learnings", "market_notes", "themes", "shoot_plan", "hooks_to_test", "collab_plan", "ad_concepts"] as const).map(k =>
                  (d[k] as string[])?.length ? <p key={k}><b className="capitalize">{k.replace(/_/g, " ")}:</b> {(d[k] as string[]).join(" · ")}</p> : null)}
              </>
            )}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="Season calendar" description="The dates the radar plans around, seeded with the plan's India dates. Editing is owner-only (PUT /marketing/studio/calendar); a screen for it is not built yet." />
        <CardBody>
          {cal.isLoading ? <Skeleton className="h-16 w-full" /> : (
            <ul className="text-sm">{(cal.data?.entries ?? []).map(e => <li key={e.name + e.start}>{e.name}: {day(e.start)} – {day(e.end)}</li>)}</ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
