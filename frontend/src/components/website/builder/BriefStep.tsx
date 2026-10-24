"use client";
// Step 1: the brief. HAIP fills in the facts (read-only here: they come from Settings, Knowledge, Bookings); the owner
// adds what only they can say. Saving the brief is what lets the sitemap run.
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Card, CardHeader } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { webError } from "@/lib/website";
import { builderApi, toLines, type BriefFacts, type BriefOwner, type BuilderState } from "@/lib/websiteBuilder";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5 py-2 sm:grid-cols-[160px_1fr] sm:gap-3">
      <dt className="text-[12px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{label}</dt>
      <dd className="text-[14px] text-[var(--haip-fg-2)]">{children}</dd>
    </div>
  );
}

const none = <span className="text-[var(--haip-fg-subtle)]">Nothing in HAIP yet</span>;

export function FactsList({ f }: { f: BriefFacts }) {
  const g = f.guests_last_year;
  return (
    <dl className="divide-y divide-[var(--haip-border)]">
      <Fact label="Business">{f.business.name}{f.business.tagline ? ` · ${f.business.tagline}` : ""}</Fact>
      <Fact label="Where">{[f.location.city, f.location.region].filter(Boolean).join(", ") || none}</Fact>
      <Fact label="Packages">{f.packages.length ? f.packages.map(p => `${p.name} (${p.length})`).join(" · ") : none}</Fact>
      <Fact label="Itineraries">{f.itineraries.length ? f.itineraries.map(i => i.name).join(" · ") : none}</Fact>
      <Fact label="Stays">{f.stays.length ? f.stays.map(s => s.name).join(" · ") : none}</Fact>
      <Fact label="Content">{f.content.approved_photos} approved photos · {f.content.faq_count} FAQs · {f.content.reviews_usable} reviews you can quote</Fact>
      <Fact label="Guests (last 12 months)">{g.enquiries ? `${g.enquiries} enquiries${g.top_cities?.length ? ` · mostly from ${g.top_cities.slice(0, 3).join(", ")}` : ""}${g.occasions && Object.keys(g.occasions).length ? ` · ${Object.keys(g.occasions).slice(0, 3).join(", ")}` : ""}` : none}</Fact>
      <Fact label="Prices on the site">{f.price_policy === "grounded" ? "Live quotes only" : "Never: guests ask on WhatsApp"}</Fact>
      <Fact label="Brand kit">{f.brand_kit.primary ? `${f.brand_kit.primary}${f.brand_kit.accent ? ` + ${f.brand_kit.accent}` : ""}${f.brand_kit.font ? ` · ${f.brand_kit.font}` : ""}` : none}</Fact>
    </dl>
  );
}

export function BriefStep({ state, onSaved }: { state: BuilderState; onSaved: (s: BuilderState) => void }) {
  const saved = state.brief?.owner;
  const facts = useQuery({ queryKey: ["web-builder-facts"], queryFn: builderApi.facts, enabled: !state.brief });
  const [goals, setGoals] = useState((saved?.goals || []).join("\n"));
  const [audience, setAudience] = useState(saved?.audience || "");
  const [tone, setTone] = useState(saved?.tone || "");
  const [must, setMust] = useState((saved?.must_haves || []).join("\n"));
  const [avoid, setAvoid] = useState((saved?.avoid || []).join(", "));
  const save = useMutation({
    mutationFn: () => {
      const owner: BriefOwner = { goals: toLines(goals).slice(0, 6), audience: audience.trim(), tone: tone.trim(),
        must_haves: toLines(must).slice(0, 8), avoid: avoid.split(",").map(x => x.trim()).filter(Boolean).slice(0, 12) };
      return builderApi.saveBrief(owner);
    },
    onSuccess: onSaved,
  });
  const f = state.brief?.facts || facts.data;
  return (
    <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
      <Card>
        <CardHeader title="What HAIP already knows" description="From your profile, packages, knowledge base, reviews and leads." />
        <div className="px-4 pb-4 sm:px-5">
          {f ? <FactsList f={f} /> : facts.isError ? <p className="py-3 text-[14px] text-[var(--haip-status-danger-fg)]">{webError(facts.error, "Couldn't load your details.")}</p>
            : <Skeleton className="h-48 w-full" />}
        </div>
      </Card>
      <Card>
        <CardHeader title="What only you can tell us" description="The art director reads this before every step." />
        <form className="grid gap-3 px-4 pb-4 sm:px-5" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
          <label className="grid gap-1 text-[13px] font-semibold text-[var(--haip-fg-2)]">What should the site achieve? (one per line)
            <textarea className={inputCls} rows={3} value={goals} onChange={e => setGoals(e.target.value)} placeholder="More weekend enquiries on WhatsApp" /></label>
          <label className="grid gap-1 text-[13px] font-semibold text-[var(--haip-fg-2)]">Who are your guests?
            <input className={inputCls} value={audience} maxLength={300} onChange={e => setAudience(e.target.value)} placeholder="Couples and young families from Bengaluru" /></label>
          <label className="grid gap-1 text-[13px] font-semibold text-[var(--haip-fg-2)]">Tone of voice
            <input className={inputCls} value={tone} maxLength={200} onChange={e => setTone(e.target.value)} placeholder="Warm, unhurried, a little poetic" /></label>
          <label className="grid gap-1 text-[13px] font-semibold text-[var(--haip-fg-2)]">Must-haves (one per line)
            <textarea className={inputCls} rows={2} value={must} onChange={e => setMust(e.target.value)} placeholder="Show the day-by-day route" /></label>
          <label className="grid gap-1 text-[13px] font-semibold text-[var(--haip-fg-2)]">Words or ideas to avoid (comma separated)
            <input className={inputCls} value={avoid} onChange={e => setAvoid(e.target.value)} placeholder="cheap, budget" /></label>
          {save.isError && <p role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">{webError(save.error, "Couldn't save the brief.")}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="submit" className={btnPrimary} disabled={save.isPending}>{save.isPending ? "Saving…" : state.brief ? "Update brief" : "Save brief"}</button>
            {state.brief && <span className={`${btn} pointer-events-none border-transparent`}>Saved</span>}
          </div>
        </form>
      </Card>
    </div>
  );
}
