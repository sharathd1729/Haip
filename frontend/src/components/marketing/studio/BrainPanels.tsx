"use client";
// Agency M2 ("brand brain + demand"): photo tags + consent, the tagging bar, approved claims, the brand voice draft and
// the demand card. Backend: endpoints/marketing_brain.py.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, day, inputCls, studioError, type Asset, type Demand } from "./types";

// ── Library ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** Tag chips under a photo, and the consent switch when it shows people. */
export function PhotoTagsRow({ a, canApprove }: { a: Asset; canApprove: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const consent = useMutation({
    mutationFn: (ok: boolean) => api.post(`${STUDIO}/media/${a.id}/people-ok`, { ok }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["studio-media"] }),
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Try again.") }),
  });
  if (!a.tags) return null;
  const subjects = a.tags.subjects.filter(s => s !== "people").slice(0, 3).map(s => s.replace("_", " "));
  return (
    <div className="space-y-1.5 px-2 pb-2">
      <p className="flex flex-wrap gap-1">
        {subjects.map(s => <span key={s} className="rounded-full bg-[var(--haip-surface)] px-2 py-0.5 text-[11px] text-[var(--haip-fg-2)]">{s}</span>)}
        {a.tags.quality >= 4 && <span className="rounded-full bg-[var(--haip-surface)] px-2 py-0.5 text-[11px] text-[var(--haip-fg-2)]">sharp</span>}
      </p>
      {a.tags.people && (a.people_ok ? (
        <p className="flex items-center justify-between gap-2 text-[11px] text-[var(--haip-fg-subtle)]">People: OK to post
          {canApprove && <button type="button" className="min-h-11 font-semibold text-primary sm:min-h-0" onClick={() => consent.mutate(false)}>Undo</button>}</p>
      ) : (
        <div className="space-y-1">
          <StatusPill tone="warning">Shows people · not used yet</StatusPill>
          {canApprove && (
            <button type="button" className={btn + " w-full"} disabled={consent.isPending} onClick={() => consent.mutate(true)}
              title="Confirm the people in this photo agreed to it being posted">They agreed: OK to post</button>
          )}
        </div>
      ))}
    </div>
  );
}

/** "12 photos not tagged yet  [Tag them]" above the library. */
export function TaggingBar() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ model: string; untagged: number; models: { key: string; label: string; enabled: boolean }[] }>({
    queryKey: ["studio-vision"], queryFn: () => api.get(`${STUDIO}/vision`).then(r => r.data),
  });
  const tag = useMutation({
    mutationFn: () => api.post(`${STUDIO}/media/tag-all`).then(r => r.data as { queued: number }),
    onSuccess: d => { toast({ variant: "success", title: `Tagging ${d.queued} photo${d.queued === 1 ? "" : "s"}`, description: "Tags appear in a minute or two." });
      setTimeout(() => { qc.invalidateQueries({ queryKey: ["studio-media"] }); qc.invalidateQueries({ queryKey: ["studio-vision"] }); }, 20000); },
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });
  if (!q.data || q.data.untagged === 0) return null;
  const label = q.data.models.find(m => m.key === q.data?.model)?.label ?? q.data.model;
  return (
    <Card className="flex flex-wrap items-center justify-between gap-2 p-3">
      <p className="text-sm text-[var(--haip-fg-2)]">{q.data.untagged} photo{q.data.untagged === 1 ? " is" : "s are"} not tagged yet.
        <span className="block text-xs text-[var(--haip-fg-subtle)]">Tags (room, view, food, light, people) help the designer pick the right photo. Uses {label}.</span></p>
      <button type="button" className={btn} disabled={tag.isPending} onClick={() => tag.mutate()}>Tag them</button>
    </Card>
  );
}

// ── Profile ────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Claim { text: string; source: string | null }

/** Facts the owner approves for public use. The copywriter may use them; the checks accept their numbers. */
export function ClaimsEditor({ value, onChange }: { value: Claim[]; onChange: (v: Claim[]) => void }) {
  const set = (i: number, patch: Partial<Claim>) => onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <div className="space-y-2">
      {value.map((c, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-[2fr_1fr_auto] sm:items-end">
          <label className="space-y-1"><span className="text-xs font-semibold text-[var(--haip-fg-2)]">Fact</span>
            <input className={inputCls} maxLength={200} placeholder="12 km from Madikeri town" value={c.text} onChange={e => set(i, { text: e.target.value })} /></label>
          <label className="space-y-1"><span className="text-xs font-semibold text-[var(--haip-fg-2)]">Source</span>
            <input className={inputCls} maxLength={200} placeholder="Google Maps" value={c.source ?? ""} onChange={e => set(i, { source: e.target.value || null })} /></label>
          <button type="button" className={btn} onClick={() => onChange(value.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      {value.length < 40 && <button type="button" className={btn} onClick={() => onChange([...value, { text: "", source: null }])}>Add a fact</button>}
    </div>
  );
}

interface Draft {
  status: "none" | "pending" | "ready" | "failed"; error?: string;
  draft?: { tagline?: string | null; audience?: string | null; tone?: string | null; usps: string[]; gaps: string[];
    voice: { trait: string; we_are: string; we_are_not: string; sounds_like: string | null; not_like: string | null }[];
    channel_tone: Record<string, string | null>; claims: Claim[] };
  sources?: Record<string, number>;
}

const SOURCE_LABELS: [string, string, string][] = [["captions", "Instagram caption", "Instagram captions"],
  ["properties", "property description", "property descriptions"], ["knowledge", "knowledge base answer", "knowledge base answers"],
  ["packages", "package", "packages"], ["destinations", "destination", "destinations"], ["itineraries", "itinerary", "itineraries"],
  ["policies", "policy", "policies"], ["ads", "ad", "ads"]];

/** "your website, 12 Instagram captions, 5 packages" from the draft's per-source counts. */
export function sourcesRead(s: Record<string, number> = {}): string {
  const parts = SOURCE_LABELS.filter(([k]) => (s[k] ?? 0) > 0).map(([k, one, many]) => `${s[k]} ${s[k] === 1 ? one : many}`);
  return [...((s.website_chars ?? 0) > 0 ? ["your website"] : []), ...parts].join(", ");
}

/** "Draft my brand voice": a suggestion from the website, Instagram, property text, knowledge base, business records and ads. Applying it fills the form;
 *  nothing is saved until the owner presses Save profile. */
export function BrandDraftPanel({ onApply }: { onApply: (d: NonNullable<Draft["draft"]>) => void }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Draft>({ queryKey: ["studio-profile-draft"], queryFn: () => api.get(`${STUDIO}/profile/draft`).then(r => r.data),
    refetchInterval: d => (d.state.data?.status === "pending" ? 4000 : false) });
  const ask = useMutation({
    mutationFn: () => api.post(`${STUDIO}/profile/draft`).then(r => r.data as Draft),
    onSuccess: d => qc.setQueryData(["studio-profile-draft"], d),
    onError: e => toast({ variant: "error", title: "Not started", description: studioError(e, "Try again.") }),
  });
  const d = q.data;
  return (
    <section className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">Draft my brand voice</h3>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Written from your website, Instagram, properties, knowledge base, packages and policies, and ads. You choose what to keep.</p>
        </div>
        <button type="button" className={btn} disabled={ask.isPending || d?.status === "pending"} onClick={() => ask.mutate()}>
          {d?.status === "pending" ? "Writing…" : d?.status === "ready" ? "Write again" : "Write a draft"}</button>
      </div>
      {q.isLoading ? <Skeleton className="h-10 w-full" /> : d?.status === "failed" ? (
        <p className="text-sm text-[var(--haip-status-danger-fg)]">{d.error}</p>
      ) : d?.status === "ready" && d.draft ? (
        <div className="space-y-2 text-sm">
          {d.draft.tone && <p><span className="font-semibold">Tone:</span> {d.draft.tone}</p>}
          {d.draft.voice.length > 0 && <ul className="space-y-1">{d.draft.voice.map((v, i) => (
            <li key={i}><span className="font-semibold">{v.trait}:</span> {v.we_are}. <span className="text-[var(--haip-fg-subtle)]">Not: {v.we_are_not}.</span></li>))}</ul>}
          {d.draft.claims.length > 0 && <p className="text-xs text-[var(--haip-fg-subtle)]">{d.draft.claims.length} fact{d.draft.claims.length === 1 ? "" : "s"} found in your own text. Check each before saving: saved facts count as approved.</p>}
          {d.sources && sourcesRead(d.sources) && <p className="text-xs text-[var(--haip-fg-subtle)]">Read: {sourcesRead(d.sources)}.</p>}
          {d.draft.gaps.length > 0 && <p className="text-xs text-[var(--haip-fg-subtle)]">Your sources don't say: {d.draft.gaps.join(" · ")}</p>}
          <button type="button" className={btnPrimary} onClick={() => d.draft && onApply(d.draft)}>Use this draft in the form</button>
        </div>
      ) : null}
    </section>
  );
}

// ── Plan ───────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The open dates and occasions the strategist was given (from bookings and the holiday calendar, not AI). */
export function DemandCard({ demand }: { demand?: Demand | null }) {
  const q = useQuery<Demand>({ queryKey: ["studio-demand"], queryFn: () => api.get(`${STUDIO}/demand`).then(r => r.data),
    enabled: !demand, staleTime: 5 * 60_000 });
  const d = demand ?? q.data;
  return (
    <Card>
      <CardHeader title="What needs selling" description="Open dates from your bookings calendar, with the long weekends and festivals around them. Not AI." />
      <CardBody>
        {!d ? (q.isLoading ? <Skeleton className="h-16 w-full" /> : <p className="text-sm text-[var(--haip-fg-subtle)]">{studioError(q.error, "Not available.")}</p>) : (
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h3 className="text-[13px] font-bold">Open dates worth marketing</h3>
              {d.gaps.length === 0 ? <p className="mt-1 text-sm text-[var(--haip-fg-subtle)]">No open weekends or holidays in the next 60 days.</p> : (
                <ul className="mt-1 space-y-1 text-sm">{d.gaps.map((g, i) => (
                  <li key={i}><span className="font-semibold">{(g.properties ?? [g.property]).join(", ")}</span> · {day(g.start)} – {day(g.end)} ({g.nights} night{g.nights === 1 ? "" : "s"})
                    <span className="block text-xs text-[var(--haip-fg-subtle)]">{g.why.join(" · ")}</span></li>))}</ul>)}
            </div>
            <div>
              <h3 className="text-[13px] font-bold">Long weekends and festivals{d.state ? ` (${d.state})` : ""}</h3>
              <ul className="mt-1 space-y-1 text-sm">
                {d.long_weekends.slice(0, 6).map((lw, i) => <li key={`l${i}`}>{day(lw.start)} – {day(lw.end)} · {lw.days} days<span className="block text-xs text-[var(--haip-fg-subtle)]">{lw.reason}</span></li>)}
                {d.occasions.filter(o => o.kind === "festival").slice(0, 4).map((o, i) => <li key={`o${i}`}>{day(o.date)} · {o.name}</li>)}
              </ul>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
