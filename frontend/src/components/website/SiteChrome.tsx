"use client";
// Website W1: the logo and the header/footer menus of a v2 site, edited by the owner without AI. Both write the v2 draft
// (site.brand, site.menus) and save at once; the server refuses a menu link that goes nowhere and the reason is shown in
// plain words (DirectEditors.saveOrExplain). Nothing is public until the owner publishes.
import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, CornerDownRight, Plus, Trash2 } from "lucide-react";
import { Drawer } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webApi } from "@/lib/website";
import type { LiveDataV2, MenuItem, Menus, SpecV2 } from "@/site-blocks/v2/types";
import { PhotoPicker } from "./PhotoPicker";
import { SECTION_NAMES, saveOrExplain } from "./DirectEditors";
import type { Draft } from "./useDraft";

const specOf = (d: unknown) => d as SpecV2;

// ─── Logo ─────────────────────────────────────────────────────────────────────────────────────────────────

export function LogoSheet({ open, onClose, draft }: { open: boolean; onClose: () => void; draft: Draft }) {
  const { toast } = useToast();
  const [picking, setPicking] = useState(false);
  const media = useQuery({ queryKey: ["web-media"], queryFn: webApi.media, enabled: open });
  const brand = draft.doc ? specOf(draft.doc).site.brand : undefined;
  const current = media.data?.find(m => m.ref === brand?.logo);
  const save = async (next: SpecV2["site"]["brand"] | undefined, done: string) => {
    draft.update(d => { const site = specOf(d).site; if (next) site.brand = next; else delete site.brand; });
    if (await saveOrExplain(draft, toast)) toast({ variant: "success", title: done });
  };
  return (
    <>
      <Drawer open={open && !picking} onOpenChange={o => !o && onClose()} title="Logo"
        description="Shown at the top of every page and in the browser tab."
        footer={<button className={btn} onClick={onClose}>Done</button>}>
        <div className="grid gap-4">
          <div className="grid min-h-28 place-items-center rounded-2xl border border-dashed border-[var(--haip-border)] bg-[var(--haip-surface)] p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {current?.url ? <img src={current.url} alt="Your logo" className="max-h-24 max-w-full object-contain" />
              : <p className="text-sm text-[var(--haip-fg-muted)]">{!brand?.logo ? "No logo yet: your business name is shown instead."
                : media.isLoading ? "Loading your logo…" : "Your logo is set. Its preview couldn't load right now."}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btnPrimary} onClick={() => setPicking(true)}>{brand?.logo ? "Change logo" : "Choose a logo"}</button>
            {brand?.logo && <button type="button" className={btn} onClick={() => save(undefined, "Logo removed. Publish to show it to guests.")}>Remove</button>}
          </div>
          {brand?.logo && (
            <label className="flex min-h-11 items-center gap-3">
              <input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={brand.show_name}
                onChange={e => save({ ...brand, show_name: e.target.checked }, "Saved. Publish to show it to guests.")} />
              <span><b className="block text-sm font-semibold">Show the business name next to the logo</b>
                <span className="text-xs text-[var(--haip-fg-muted)]">Turn this off if your logo already spells the name.</span></span>
            </label>
          )}
          <p className="text-xs text-[var(--haip-fg-muted)]">Best: a PNG with a see-through background, at least 400 pixels wide.</p>
        </div>
      </Drawer>
      <PhotoPicker open={picking} onClose={() => setPicking(false)} media={media.data || []} loading={media.isLoading} title="Choose your logo"
        selected={brand?.logo || null} onPick={ref => save({ logo: ref, show_name: brand?.show_name ?? true }, "Logo saved. Publish to show it to guests.")} />
    </>
  );
}

// ─── Menu and footer ──────────────────────────────────────────────────────────────────────────────────────

type Row = MenuItem & { children?: MenuItem[] };
const WEB = "web";

/** The links a site shows today when it has no menus of its own (SiteRendererV2.navLinks): pages marked nav. */
export function defaultMenus(doc: SpecV2): Menus {
  const pages = doc.pages.filter(p => p.nav && p.slug !== "/").map(p => ({ label: p.title, to: p.slug }));
  return { main: pages.map(p => ({ ...p, children: [] })), footer: [{ label: "Home", to: "/" }, ...pages, { label: "Policies", to: "/policies" }] };
}

/** Every place on the site a link can go: pages, parts of a page, each stay's page, the policies page. */
function destinations(doc: SpecV2, live: LiveDataV2 | undefined): { group: string; items: [string, string][] }[] {
  const pages: [string, string][] = doc.pages.map(p => [p.slug, p.title]);
  const parts: [string, string][] = doc.pages.flatMap(p => p.sections.filter(s => s.type !== "hero")
    .map(s => [`${p.slug}#${s.id}`, `${p.title} › ${SECTION_NAMES[s.type]?.[0] || s.type}`] as [string, string]));
  const stays: [string, string][] = (live?.stays_index || []).filter(s => s.slug).map(s => [`/stays/${s.slug}`, s.name]);
  const search: [string, string][] = stays.length ? [["/stays", "Find your stay (search)"]] : [];
  return [{ group: "Pages", items: [...pages, ...search, ["/policies", "Policies"]] }, { group: "Part of a page", items: parts },
    ...(stays.length ? [{ group: "Your stays", items: stays }] : [])];
}

export function MenuSheet({ open, onClose, draft }: { open: boolean; onClose: () => void; draft: Draft }) {
  const { toast } = useToast();
  const doc = draft.doc ? specOf(draft.doc) : null;
  const live = useQuery({ queryKey: ["web-live"], queryFn: webApi.live, enabled: open });
  const [which, setWhich] = useState<"main" | "footer">("main");
  const [menus, setMenus] = useState<Menus | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open && doc) setMenus(structuredClone(doc.site.menus || defaultMenus(doc))); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps -- start from the saved menus each time
  if (!doc || !menus) return null;
  const dests = destinations(doc, live.data as unknown as LiveDataV2 | undefined);
  const known = new Set(dests.flatMap(g => g.items.map(([v]) => v)));
  const rows: Row[] = menus[which];
  const set = (next: Row[]) => setMenus({ ...menus, [which]: next } as Menus);
  const blank = (): Row => ({ label: "", to: doc.pages[0].slug, ...(which === "main" ? { children: [] } : {}) });
  const bad = [...rows, ...rows.flatMap(r => r.children || [])].filter(r => !r.label.trim() || (!r.to.startsWith("/") && !/^https:\/\/\S+\.\S+/.test(r.to)));
  const save = async () => {
    setBusy(true);
    draft.update(d => { specOf(d).site.menus = menus; });
    const ok = await saveOrExplain(draft, toast);
    setBusy(false);
    if (ok) { toast({ variant: "success", title: "Menus saved. Publish to show them to guests." }); onClose(); }
  };
  const reset = async () => {
    draft.update(d => { delete specOf(d).site.menus; });
    if (await saveOrExplain(draft, toast)) { toast({ variant: "success", title: "Back to listing your pages." }); onClose(); }
  };
  return (
    <Drawer open={open} onOpenChange={o => !o && onClose()} title="Menu and footer" wide
      description="The same links show on every page. On phones the header menu opens from the ☰ button."
      footer={<div className="flex flex-wrap gap-2">
        {doc.site.menus && <button className={btn} onClick={reset}>Use my pages instead</button>}
        <button className={btn} onClick={onClose}>Cancel</button>
        <button className={btnPrimary} disabled={busy || bad.length > 0} onClick={save}>{busy ? "Saving…" : "Save"}</button></div>}>
      <div className="grid gap-4">
        <div className="inline-flex justify-self-start overflow-hidden rounded-full border border-[var(--haip-border)]" role="group" aria-label="Which menu">
          {([["main", "Top of the page"], ["footer", "Bottom of the page"]] as const).map(([k, label]) => (
            <button key={k} type="button" aria-pressed={which === k} onClick={() => setWhich(k)}
              className={`min-h-11 px-4 text-sm ${which === k ? "bg-[var(--haip-primary-tint)] font-semibold" : ""}`}>{label}</button>))}
        </div>
        {!rows.length && <p className="text-sm text-[var(--haip-fg-muted)]">No links here yet.</p>}
        <ol className="grid gap-2">
          {rows.map((r, i) => (
            <li key={i} className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3">
              <LinkFields item={r} dests={dests} known={known}
                onChange={v => set(rows.map((x, j) => (j === i ? { ...x, ...v } : x)))}
                onMove={by => { const n = [...rows]; [n[i], n[i + by]] = [n[i + by], n[i]]; set(n); }}
                first={i === 0} last={i === rows.length - 1} onRemove={() => set(rows.filter((_, j) => j !== i))} />
              {which === "main" && (
                <div className="grid gap-2 pl-4 sm:pl-8">
                  {(r.children || []).map((c, ci) => (
                    <div key={ci} className="grid grid-cols-[auto_1fr] gap-2"><CornerDownRight size={18} aria-hidden="true" className="mt-3 text-[var(--haip-fg-muted)]" />
                      <LinkFields item={c} dests={dests} known={known} first={ci === 0} last={ci === (r.children || []).length - 1}
                        onChange={v => set(rows.map((x, j) => (j === i ? { ...x, children: (x.children || []).map((y, k) => (k === ci ? { ...y, ...v } : y)) } : x)))}
                        onMove={by => set(rows.map((x, j) => { if (j !== i) return x; const n = [...(x.children || [])]; [n[ci], n[ci + by]] = [n[ci + by], n[ci]]; return { ...x, children: n }; }))}
                        onRemove={() => set(rows.map((x, j) => (j === i ? { ...x, children: (x.children || []).filter((_, k) => k !== ci) } : x)))} />
                    </div>))}
                  {(r.children || []).length < 8 && (
                    <button type="button" className="flex min-h-11 items-center gap-1.5 justify-self-start text-sm font-semibold text-[var(--primary)]"
                      onClick={() => set(rows.map((x, j) => (j === i ? { ...x, children: [...(x.children || []), { label: "", to: doc.pages[0].slug }] } : x)))}>
                      <Plus size={16} aria-hidden="true" />Add a link under it</button>)}
                </div>
              )}
            </li>
          ))}
        </ol>
        {rows.length < (which === "main" ? 8 : 12) && (
          <button type="button" className={`${btn} justify-self-start`} onClick={() => set([...rows, blank()])}><Plus size={16} aria-hidden="true" />Add link</button>)}
        {bad.length > 0 && <p className="text-sm font-semibold" role="alert">Every link needs a name, and a web link must start with https://</p>}
      </div>
    </Drawer>
  );
}

function LinkFields({ item, dests, known, onChange, onMove, onRemove, first, last }: {
  item: MenuItem; dests: ReturnType<typeof destinations>; known: Set<string>; onChange: (v: Partial<MenuItem>) => void;
  onMove: (by: number) => void; onRemove: () => void; first: boolean; last: boolean;
}) {
  const web = !item.to.startsWith("/");
  const choice = web ? WEB : item.to;
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto]">
      <label className="grid gap-1"><span className="text-xs font-semibold">Name in the menu</span>
        <input className={inputCls} maxLength={40} value={item.label} onChange={e => onChange({ label: e.target.value })} /></label>
      <label className="grid gap-1"><span className="text-xs font-semibold">Goes to</span>
        <select className={inputCls} value={choice} onChange={e => onChange({ to: e.target.value === WEB ? "https://" : e.target.value })}>
          {!web && !known.has(item.to) && <option value={item.to}>{item.to}</option>}
          {dests.map(g => <optgroup key={g.group} label={g.group}>{g.items.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</optgroup>)}
          <option value={WEB}>A web link…</option>
        </select>
        {web && <input className={inputCls} inputMode="url" maxLength={300} aria-label="Web link" placeholder="https://"
          value={item.to} onChange={e => onChange({ to: e.target.value.trim() })} />}
      </label>
      <div className="flex items-end">
        <IconBtn label="Move up" disabled={first} onClick={() => onMove(-1)}><ArrowUp size={18} /></IconBtn>
        <IconBtn label="Move down" disabled={last} onClick={() => onMove(1)}><ArrowDown size={18} /></IconBtn>
        <IconBtn label="Remove" onClick={onRemove}><Trash2 size={18} /></IconBtn>
      </div>
    </div>
  );
}

function IconBtn({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick}
    className="grid h-11 w-11 shrink-0 place-items-center rounded-lg hover:bg-[var(--haip-surface)] disabled:opacity-30">{children}</button>;
}
