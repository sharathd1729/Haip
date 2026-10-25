"use client";
// Change the website yourself, no AI (owner, Oct 2026: "I can't change the photo or colours myself"): the big photo,
// colours and fonts, which sections show and in what order, and every heading and text. Each sheet edits the v2 draft
// (useDraft.update) and saves it at once; the server checks it (readable colours, no typed prices) and a refusal is
// shown in plain words with the draft put back as it was. Nothing is public until the owner publishes.
import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Drawer } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { errorProblems, webApi, webError } from "@/lib/website";
import { CATALOGUE, type SectionType, type SectionV2, type SpecV2 } from "@/site-blocks/v2/types";
import { PhotoPicker } from "./PhotoPicker";
import type { Draft } from "./useDraft";

type Palette = SpecV2["tokens"]["palette"];

/** What each section is called on this screen. */
export const SECTION_NAMES: Record<SectionType, [string, string]> = {
  hero: ["Top of the page", "Big photo, headline and a WhatsApp button."],
  stays: ["Your stays", "Your caravans, villas or rooms from Properties."],
  booking: ["Check dates", "Guests pick dates and send them to you."],
  packages: ["Trips and packages", "Your published packages."],
  itinerary: ["Day-by-day route", "One published itinerary, day by day."],
  gallery: ["Photos", "Your approved photos."],
  reviews: ["Guest reviews", "Reviews guests agreed to share."],
  faq: ["Questions and answers", "Approved answers from your Knowledge base."],
  contact: ["Contact and map", "Phone, WhatsApp, email and address."],
  "booking-cta": ["Message us banner", "A band asking guests to message you."],
  text: ["Your own text", "Anything you want to say: your story, house rules, directions."],
};

// The text each section type lets you write (backend app/schemas/site_spec.py SLOTS; change both together).
const FIELDS: Record<SectionType, string[]> = {
  hero: ["eyebrow", "headline", "subhead", "cta_label"],
  stays: ["eyebrow", "heading", "intro"],
  booking: ["eyebrow", "heading", "intro", "cta_label"],
  packages: ["eyebrow", "heading", "intro"],
  itinerary: ["eyebrow", "heading", "intro"],
  gallery: ["eyebrow", "heading"],
  reviews: ["eyebrow", "heading"],
  faq: ["eyebrow", "heading"],
  contact: ["eyebrow", "heading", "text"],
  "booking-cta": ["heading", "text", "cta_label"],
  text: ["eyebrow", "heading", "body"],
};
const FIELD: Record<string, [string, number, string?]> = {
  eyebrow: ["Small line above the heading", 60],
  heading: ["Heading", 90],
  headline: ["Big headline", 90, "Put *stars* around a word to show it in your highlight colour."],
  subhead: ["Line under the headline", 240],
  intro: ["Short introduction", 280],
  text: ["Text", 280],
  body: ["Your text", 1200, "Leave an empty line to start a new paragraph."],
  cta_label: ["Button text", 40],
};

const home = (d: unknown) => (d as SpecV2).pages[0];

/** Saves the draft now; on a refusal shows why (in plain words) and puts the draft back. True when saved. */
async function saveOrExplain(draft: Draft, toast: ReturnType<typeof useToast>["toast"], words = plainProblems) {
  const err = await draft.flush();
  if (!err) return true;
  toast({ variant: "error", title: "Not saved", description: words(err) });
  draft.load();
  return false;
}

/** The server's problems without the technical "pages.0.sections.1.slots:" place, e.g. "a price was typed into …". */
export function plainProblems(e: unknown): string {
  const p = errorProblems(e).map(x => x.replace(/^[\w.-]+: /, "")
    .replace(/^a price was typed into .*\('(.+)'\).*$/, "Please take out \"$1\": prices can't be typed. HAIP shows your live prices by itself."));
  return p.length ? p.join(" ") : webError(e, "Try again.");
}

// ─── Photos: the big photo at the top ─────────────────────────────────────────────────────────────────────

export function PhotosSheet({ open, onClose, draft }: { open: boolean; onClose: () => void; draft: Draft }) {
  const { toast } = useToast();
  const media = useQuery({ queryKey: ["web-media"], queryFn: webApi.media, enabled: open });
  const hero = draft.doc ? home(draft.doc).sections.find(s => s.type === "hero") : undefined;
  const pick = async (ref: string) => {
    draft.update(d => { const h = home(d).sections.find(s => s.type === "hero"); if (h) h.slots.media = ref; });
    if (await saveOrExplain(draft, toast)) toast({ variant: "success", title: "Photo changed. Publish to show it to guests." });
  };
  return (
    <PhotoPicker open={open && !!hero} onClose={onClose} media={media.data || []} loading={media.isLoading} onPick={pick}
      title="The big photo at the top" selected={typeof hero?.slots.media === "string" ? hero.slots.media : null} />
  );
}

// ─── Colours & font ───────────────────────────────────────────────────────────────────────────────────────

const COLOURS: [keyof Omit<Palette, "name">, string, string][] = [
  ["surface", "Background", "The page behind everything."],
  ["ink", "Text", "Headings and writing."],
  ["primary", "Buttons", "Buttons and links."],
  ["accent", "Highlight", "Starred words and small lines."],
];
const RULE_WORDS: [RegExp, string][] = [
  [/^ink on surface/, "Text on the background"],
  [/^muted text on surface/, "Small grey text on the background"],
  [/^muted text on the alternate band/, "Small grey text on the shaded bands"],
  [/^primary \(links/, "The button colour on the background"],
  [/^primary on the alternate band/, "The button colour on the shaded bands"],
  [/^button text on primary/, "Writing on the buttons"],
  [/^accent/, "The highlight colour on the background"],
];

/** "tokens.palette: … ink on surface: 1.60:1, needs 4.5:1; …" -> "Text on the background is hard to read (1.6 to 1, needs 4.5). …" */
export function contrastWords(problems: string[]): string {
  const out: string[] = [];
  for (const m of problems.join("; ").matchAll(/([a-z][a-z ,()]+?): ([\d.]+):1, needs ([\d.]+):1/g)) {
    const name = RULE_WORDS.find(([re]) => re.test(m[1].trim()))?.[1];
    if (name) out.push(`${name} is hard to read (${Number(m[2]).toFixed(1)} to 1, needs ${m[3]}).`);
  }
  return out.length ? `${out.join(" ")} Make one of those colours darker or lighter.` : "";
}

const RADII: [SpecV2["tokens"]["radius"], string][] = [["soft", "Rounded"], ["sharp", "Square"], ["pill", "Very round"]];

export function LookSheet({ open, onClose, draft }: { open: boolean; onClose: () => void; draft: Draft }) {
  const { toast } = useToast();
  const tokens = (draft.doc as unknown as SpecV2 | null)?.tokens;
  const [t, setT] = useState(tokens);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setT(tokens); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps -- start from the saved look each time
  const setColour = (k: keyof Omit<Palette, "name">, v: string) => t && setT({ ...t, palette: { ...t.palette, name: "custom", [k]: v.toUpperCase() } });
  const save = async () => {
    if (!t) return;
    setBusy(true);
    draft.update(d => { (d as unknown as SpecV2).tokens = { ...t, palette: { ...t.palette, name: t.palette.name || "custom" } }; });
    const ok = await saveOrExplain(draft, toast, e => contrastWords(errorProblems(e)) || webError(e, "Try again."));
    setBusy(false);
    if (ok) { toast({ variant: "success", title: "Saved. Publish to show it to guests." }); onClose(); }
  };
  return (
    <Drawer open={open} onOpenChange={o => !o && onClose()} title="Colours & font" wide
      footer={<div className="flex gap-2"><button className={btn} onClick={onClose}>Cancel</button>
        <button className={btnPrimary} disabled={busy || !t} onClick={save}>{busy ? "Saving…" : "Save"}</button></div>}>
      {t && <div className="grid gap-6">
        <fieldset className="grid gap-2"><legend className="mb-2 font-semibold">Ready-made colours</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(CATALOGUE.palettes).map(([key, p]) => (
              <button key={key} type="button" aria-pressed={t.palette.name === key} onClick={() => setT({ ...t, palette: { name: key, ink: p.ink, surface: p.surface, primary: p.primary, accent: p.accent } })}
                className={`grid min-h-11 gap-2 rounded-xl border p-3 text-left text-sm ${t.palette.name === key ? "border-[var(--primary)] ring-2 ring-[var(--primary)]" : "border-[var(--haip-border)]"}`}>
                <Swatches p={p} />{p.label}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset className="grid gap-3"><legend className="mb-1 font-semibold">Or pick your own</legend>
          {COLOURS.map(([k, label, hint]) => (
            <label key={k} className="grid grid-cols-[56px_1fr] items-center gap-3">
              <input type="color" value={t.palette[k]} onChange={e => setColour(k, e.target.value)}
                className="h-11 w-14 cursor-pointer rounded-lg border border-[var(--haip-border)] bg-transparent p-1" />
              <span><b className="block text-sm font-semibold">{label}</b><span className="text-xs text-[var(--haip-fg-muted)]">{hint} {t.palette[k]}</span></span>
            </label>
          ))}
          <p className="text-xs text-[var(--haip-fg-muted)]">HAIP checks every colour can be read easily, also on phones in sunlight, before it saves.</p>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1"><span className="text-sm font-semibold">Heading font</span>
            <select className={inputCls} value={t.display} onChange={e => setT({ ...t, display: e.target.value })}>
              {Object.entries(CATALOGUE.fonts.display).map(([k, f]) => <option key={k} value={k}>{f.family}</option>)}</select></label>
          <label className="grid gap-1"><span className="text-sm font-semibold">Text font</span>
            <select className={inputCls} value={t.body} onChange={e => setT({ ...t, body: e.target.value })}>
              {Object.entries(CATALOGUE.fonts.body).map(([k, f]) => <option key={k} value={k}>{f.family}</option>)}</select></label>
        </div>
        <fieldset><legend className="mb-2 text-sm font-semibold">Corners of buttons and photos</legend>
          <div className="flex flex-wrap gap-2">{RADII.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={t.radius === k} onClick={() => setT({ ...t, radius: k })}
              className={`min-h-11 rounded-xl border px-4 text-sm ${t.radius === k ? "border-[var(--primary)] bg-[var(--haip-primary-tint)] font-semibold" : "border-[var(--haip-border)]"}`}>{label}</button>))}
          </div></fieldset>
      </div>}
    </Drawer>
  );
}

// Colours are the owner's own data, so they are painted inline.
function Swatches({ p }: { p: Omit<Palette, "name"> }) {
  return (
    <span className="flex overflow-hidden rounded-lg border border-[var(--haip-border)]" aria-hidden="true">
      {[p.surface, p.ink, p.primary, p.accent].map((c, i) => <span key={i} className="h-6 flex-1" style={{ background: c }} />)}
    </span>
  );
}

// ─── Sections: order, remove, add ─────────────────────────────────────────────────────────────────────────

function newId(doc: SpecV2, type: SectionType): string {
  const ids = new Set(doc.pages.flatMap(p => p.sections.map(s => s.id)));
  const base = type === "booking-cta" ? "cta" : type;
  let id = base, n = 2;
  while (ids.has(id)) id = `${base}-${n++}`;
  return id;
}

export function SectionsSheet({ open, onClose, draft, onWrite }: { open: boolean; onClose: () => void; draft: Draft; onWrite: (id: string) => void }) {
  const [adding, setAdding] = useState(false);
  const page = draft.doc ? home(draft.doc) : null;
  const contacts = page?.sections.filter(s => s.type === "contact").length ?? 0;
  const move = (i: number, by: number) => draft.update(d => { const s = home(d).sections; [s[i], s[i + by]] = [s[i + by], s[i]]; });
  const remove = (i: number) => draft.update(d => { home(d).sections.splice(i, 1); });
  const add = (type: SectionType) => {
    const doc = draft.doc as unknown as SpecV2;
    const sec = CATALOGUE.sections[type];
    const id = newId(doc, type);
    draft.update(d => {
      const s = home(d).sections;
      const at = s.findIndex(x => x.type === "booking-cta" || x.type === "contact");
      s.splice(at < 0 ? s.length : at, 0, { id, type, variant: sec.variants[0], source: sec.source, slots: type === "hero" ? { headline: doc.site.name } : {} });
    });
    setAdding(false);
    if (type === "text") onWrite(id);
  };
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) { setAdding(false); onClose(); } }} title={adding ? "Add a section" : "Sections"}
      description={adding ? "It goes above your contact details. You can move it after." : "Top to bottom, as guests see your home page. Changes save by themselves."}
      footer={adding ? <button className={btn} onClick={() => setAdding(false)}>Back</button>
        : <button className={btnPrimary} onClick={() => setAdding(true)}><Plus size={16} aria-hidden="true" />Add a section</button>}>
      {!page ? null : adding ? (
        <ul className="grid gap-2">{(Object.keys(SECTION_NAMES) as SectionType[]).map(t => (
          <li key={t}><button type="button" onClick={() => add(t)} className="grid min-h-11 w-full rounded-xl border border-[var(--haip-border)] p-3 text-left">
            <b className="font-semibold">{SECTION_NAMES[t][0]}</b><span className="text-sm text-[var(--haip-fg-muted)]">{SECTION_NAMES[t][1]}</span></button></li>))}
        </ul>
      ) : (
        <ol className="grid gap-2">{page.sections.map((s, i) => (
          <li key={s.id} className="flex min-w-0 items-center gap-1 rounded-xl border border-[var(--haip-border)] p-2 pl-3">
            <button type="button" className="min-h-11 min-w-0 flex-1 text-left" onClick={() => onWrite(s.id)}>
              <b className="block truncate font-semibold">{SECTION_NAMES[s.type]?.[0] || s.type}</b>
              <span className="block truncate text-sm text-[var(--haip-fg-muted)]">{headingOf(s) || "Tap to change the words"}</span></button>
            <IconBtn label="Move up" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={18} /></IconBtn>
            <IconBtn label="Move down" disabled={i === page.sections.length - 1} onClick={() => move(i, 1)}><ArrowDown size={18} /></IconBtn>
            <IconBtn label="Remove" disabled={s.type === "contact" && contacts === 1 || page.sections.length === 1} onClick={() => remove(i)}><Trash2 size={18} /></IconBtn>
          </li>))}
        </ol>
      )}
    </Drawer>
  );
}

const headingOf = (s: SectionV2) => String(s.slots.headline || s.slots.heading || s.slots.eyebrow || "").replace(/\*/g, "");   // *word* = emphasis on the site

function IconBtn({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick}
    className="grid h-11 w-11 shrink-0 place-items-center rounded-lg hover:bg-[var(--haip-surface)] disabled:opacity-30">{children}</button>;
}

// ─── Words: every heading and text of one section ─────────────────────────────────────────────────────────

export function WordsSheet({ open, onClose, draft, sectionId }: { open: boolean; onClose: () => void; draft: Draft; sectionId: string | null }) {
  const { toast } = useToast();
  const page = draft.doc ? home(draft.doc) : null;
  const [id, setId] = useState<string | null>(sectionId);
  const [slots, setSlots] = useState<Record<string, unknown>>({});
  const [variant, setVariant] = useState("");
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const media = useQuery({ queryKey: ["web-media"], queryFn: webApi.media, enabled: picking });
  const choose = (sid: string | null) => {
    const s = page?.sections.find(x => x.id === sid) || page?.sections[0];
    setId(s?.id || null); setSlots({ ...(s?.slots || {}) }); setVariant(s?.variant || "");
  };
  useEffect(() => { if (open) choose(sectionId); }, [open, sectionId]); // eslint-disable-line react-hooks/exhaustive-deps
  const sec = page?.sections.find(x => x.id === id);
  // The headline and button text can't be empty (the server would refuse it in less friendly words).
  const empty = sec ? FIELDS[sec.type].filter(k => (k === "headline" || k === "cta_label") && !String(slots[k] ?? "").trim()).map(k => FIELD[k][0]) : [];
  const save = async () => {
    if (!sec || empty.length) return;
    setBusy(true);
    draft.update(d => { const s = home(d).sections.find(x => x.id === sec.id); if (s) { s.slots = { ...s.slots, ...slots }; s.variant = variant || s.variant; } });
    const ok = await saveOrExplain(draft, toast);
    setBusy(false);
    if (ok) { toast({ variant: "success", title: "Saved. Publish to show it to guests." }); onClose(); }
  };
  return (
    <>
      <Drawer open={open && !picking} onOpenChange={o => !o && onClose()} title="Words"
        footer={<div className="flex gap-2"><button className={btn} onClick={onClose}>Cancel</button>
          <button className={btnPrimary} disabled={busy || !sec || empty.length > 0} onClick={save}>{busy ? "Saving…" : "Save"}</button></div>}>
        {page && sec && <div className="grid gap-4">
          <label className="grid gap-1"><span className="text-sm font-semibold">Which part of the page</span>
            <select className={inputCls} value={sec.id} onChange={e => choose(e.target.value)}>
              {page.sections.map((s, i) => <option key={s.id} value={s.id}>{i + 1}. {SECTION_NAMES[s.type]?.[0] || s.type}{headingOf(s) ? `: ${headingOf(s)}` : ""}</option>)}
            </select></label>
          {(FIELDS[sec.type] || []).map(k => {
            const [label, max, hint] = FIELD[k];
            const value = String(slots[k] ?? "");
            const long = max > 90;
            return (
              <label key={k} className="grid gap-1"><span className="text-sm font-semibold">{label}</span>
                {long ? <textarea className={`${inputCls} min-h-28`} rows={k === "body" ? 8 : 3} maxLength={max} value={value} onChange={e => setSlots({ ...slots, [k]: e.target.value })} />
                  : <input className={inputCls} maxLength={max} value={value} onChange={e => setSlots({ ...slots, [k]: e.target.value })} />}
                <span className="text-xs text-[var(--haip-fg-muted)]">{hint ? `${hint} ` : ""}{value.length} / {max}</span></label>
            );
          })}
          {sec.type === "text" && (
            <fieldset className="grid gap-2"><legend className="mb-1 text-sm font-semibold">Photo</legend>
              <div className="flex flex-wrap gap-2">{[["plain", "Words only"], ["with-photo", "Words and a photo"]].map(([v, label]) => (
                <button key={v} type="button" aria-pressed={variant === v} onClick={() => setVariant(v)}
                  className={`min-h-11 rounded-xl border px-4 text-sm ${variant === v ? "border-[var(--primary)] bg-[var(--haip-primary-tint)] font-semibold" : "border-[var(--haip-border)]"}`}>{label}</button>))}
              </div>
              {variant === "with-photo" && <button type="button" className={btn} onClick={() => setPicking(true)}>{slots.media ? "Change the photo" : "Choose a photo"}</button>}
            </fieldset>
          )}
          {empty.length > 0 && <p className="text-sm font-semibold" role="alert">Fill in: {empty.join(", ")}.</p>}
          <p className="text-xs text-[var(--haip-fg-muted)]">Prices can&apos;t be typed here: they come from your live HAIP prices.</p>
        </div>}
      </Drawer>
      <PhotoPicker open={picking} onClose={() => setPicking(false)} media={media.data || []} loading={media.isLoading}
        selected={typeof slots.media === "string" ? slots.media : null} onPick={ref => setSlots({ ...slots, media: ref })} />
    </>
  );
}
