"use client";
// Website W2: the on-page editor for a v2 site (owner, Nov 2026: "first clients use a visual editor; AI only if they want a
// change"). The real site renders at desktop / tablet / phone width; click any part to change it on the right; the block
// list on the left adds, moves, copies and removes parts. Edits go into the one draft (useDraft: autosave, undo, conflict
// check); nothing is public until the owner publishes. Phones keep the simple Website screen (too small to edit on).
import Link from "next/link";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Copy, ExternalLink, MoreHorizontal, Plus, Redo2, Trash2, Undo2, ArrowUp, ArrowDown } from "lucide-react";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { webApi, type SiteOut } from "@/lib/website";
import type { SiteEnv } from "@/site-blocks/types";
import { SiteRendererV2 } from "@/site-blocks/v2/SiteRendererV2";
import type { LiveDataV2, PageV2, SectionType, SectionV2, SpecV2 } from "@/site-blocks/v2/types";
import { ChangeSheet } from "../ChangeSheet";
import { SECTION_NAMES, headingOf, plainProblems } from "../DirectEditors";
import { SAVE_LABEL, useIsPhone } from "../Editor";
import { useDraft } from "../useDraft";
import { PageInspector, SectionInspector } from "./Inspector";
import { addPage, addSection, duplicateSection, moveSection, removePage, removeSection, sameTarget, sectionsOf, type Target } from "./targets";
import { TemplateBar, templateLabel, templatePage, TEMPLATE_TYPES, useTemplatePreview } from "./templates";
import { TEMPLATE_SHARED, templateOf } from "@/site-blocks/v2/types";

const DEVICES = { desktop: 1200, tablet: 768, phone: 390 } as const;
type Device = keyof typeof DEVICES;
const spec = (d: unknown) => d as SpecV2;

export function CanvasEditorV2({ site }: { site: SiteOut }) {
  const draft = useDraft();
  const phone = useIsPhone();
  const doc = draft.doc ? spec(draft.doc) : null;
  const live = useQuery({ queryKey: ["web-live-v2", draft.version?.sha256], queryFn: webApi.live, enabled: !!draft.version, placeholderData: keepPreviousData });
  const media = useQuery({ queryKey: ["web-media"], queryFn: webApi.media });
  const preview = useQuery({ queryKey: ["web-preview", draft.version?.sha256], queryFn: webApi.preview, enabled: !!draft.version, staleTime: 60 * 60 * 1000 });
  const [target, setTarget] = useState<Target>({ kind: "page", slug: "/" });
  const [sel, setSel] = useState<string | null>(null);
  const [device, setDevice] = useState<Device>("desktop");
  const [adding, setAdding] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [aiFor, setAiFor] = useState<SectionV2 | null>(null);
  const tpl = useTemplatePreview(target, live.data as unknown as LiveDataV2 | undefined);

  const sections = doc ? sectionsOf(doc, target) || [] : [];
  const section = sections.find(s => s.id === sel) || null;
  const page: PageV2 | null = !doc ? null : target.kind === "page" ? doc.pages.find(p => p.slug === target.slug) || null : templatePage(doc, target.key);
  useEffect(() => { if (doc && target.kind === "page" && !doc.pages.some(p => p.slug === target.slug)) setTarget({ kind: "page", slug: "/" }); }, [doc, target]);

  const env = useMemo<SiteEnv>(() => ({ mode: "editor", base: "", apiBase: null, query: {}, stay: tpl.stay, packageKey: tpl.packageKey,
    assets: Object.fromEntries((media.data || []).filter(m => m.url).map(m => [m.id, { src: m.url as string, alt: m.alt_text || "" }])) }), [media.data, tpl.stay, tpl.packageKey]);
  const liveData = useMemo<LiveDataV2 | null>(() => (live.data && doc ? { ...(live.data as unknown as LiveDataV2), doc } : null), [live.data, doc]);

  const edit = (fn: (d: SpecV2) => void) => draft.update(d => fn(spec(d)));
  const select = (id: string | null) => { setSel(id); setMenuFor(null); };

  if (phone) {
    return (
      <div className="mx-auto grid max-w-[520px] gap-3 p-6 text-center">
        <p className="text-lg font-semibold">On-page editing needs a bigger screen</p>
        <p className="text-sm text-[var(--haip-fg-muted)]">On a phone, use the buttons on the Website page to change photos, words, colours and menus.</p>
        <Link className={btnPrimary} href="/dashboard/marketing/website">Back to Website</Link>
      </div>
    );
  }
  if (draft.loadError) return <p className="p-6 text-sm">Couldn&apos;t load your website draft. <button className="underline" onClick={() => draft.load()}>Try again</button></p>;
  if (!doc || !page) return <div className="h-[70vh] animate-pulse bg-[var(--haip-surface)]" aria-label="Loading the editor" />;

  const pages = doc.pages;
  const newPage = () => {
    const title = window.prompt("Name of the new page (for example: Our story)")?.trim();
    if (!title) return;
    let slug: string | null = null;
    edit(d => { slug = addPage(d, title); });
    if (slug) { setTarget({ kind: "page", slug }); select(null); }
  };
  const targets: [string, Target][] = [...pages.map(p => [p.title + (p.slug === "/" ? " (home)" : ""), { kind: "page", slug: p.slug }] as [string, Target]),
    ...TEMPLATE_TYPES.map(k => [templateLabel(k), { kind: "template", key: k }] as [string, Target])];

  return (
    <div className="flex h-[calc(100dvh-64px)] min-h-[600px] flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2">
        <Link href="/dashboard/marketing/website" aria-label="Back to Website" className="grid h-11 w-11 place-items-center rounded-lg hover:bg-[var(--haip-surface)]"><ArrowLeft size={20} /></Link>
        <div className="mr-2 grid leading-tight"><b className="text-[15px]">{doc.site.name}</b>
          <span className={`text-xs ${draft.state === "error" || draft.state === "conflict" ? "font-semibold text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-muted)]"}`}>{SAVE_LABEL[draft.state]}</span></div>
        <label className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]">Page
          <select className={`${inputCls} min-h-10 w-auto`} value={targets.findIndex(([, t]) => sameTarget(t, target))}
            onChange={e => { const v = Number(e.target.value); if (v === -1) newPage(); else { setTarget(targets[v][1]); select(null); } }}>
            {targets.map(([label], i) => <option key={i} value={i}>{label}</option>)}
            {pages.length < 12 && <option value={-1}>+ New page…</option>}
          </select></label>
        <div role="radiogroup" aria-label="Screen size" className="mx-auto inline-flex overflow-hidden rounded-full border border-[var(--haip-border)]">
          {(Object.keys(DEVICES) as Device[]).map(k => (
            <button key={k} type="button" role="radio" aria-checked={device === k} onClick={() => setDevice(k)}
              className={`min-h-10 px-4 text-sm capitalize ${device === k ? "bg-[var(--haip-primary-tint)] font-semibold" : ""}`}>{k}</button>))}
        </div>
        <button type="button" className={btn} aria-label="Undo" onClick={() => draft.undo()}><Undo2 size={16} /></button>
        <button type="button" className={btn} aria-label="Redo" onClick={() => draft.redo()}><Redo2 size={16} /></button>
        {preview.data && <a className={btn} href={preview.data.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={16} aria-hidden="true" />Preview</a>}
        <Link className={btnPrimary} href="/dashboard/marketing/website">Done</Link>
      </header>
      {(draft.state === "error" || draft.state === "conflict") && (
        <div role="alert" className="flex flex-wrap items-center gap-3 bg-[var(--haip-status-danger-bg)] px-4 py-2 text-sm text-[var(--haip-status-danger-fg)]">
          <span className="min-w-0 flex-1">{draft.state === "conflict" ? "Someone else changed this website. Reload to see their version." : plainProblems(draft.error) || "That change wasn't saved."}</span>
          {draft.state === "conflict" ? <button className={btn} onClick={() => draft.load()}>Reload</button> : <button className={btn} onClick={() => draft.undo()}>Undo it</button>}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside aria-label="Parts of this page" className="relative flex w-[248px] shrink-0 flex-col gap-1 overflow-y-auto border-r border-[var(--haip-border)] bg-[var(--haip-card)] p-3">
          <div className="flex items-center justify-between gap-2 pb-2">
            <span className="grid leading-tight"><b className="text-sm">{target.kind === "page" ? page.title : templateLabel(target.key)}</b>
              <span className="text-xs text-[var(--haip-fg-muted)]">{sections.length} part{sections.length === 1 ? "" : "s"}</span></span>
            <button type="button" aria-expanded={adding} onClick={() => setAdding(a => !a)} disabled={sections.length >= 20}
              className="flex min-h-10 items-center gap-1 rounded-full border border-[var(--haip-border)] px-3 text-sm font-semibold"><Plus size={15} aria-hidden="true" />Add</button>
          </div>
          {target.kind === "template" && <TemplateBar target={target} tpl={tpl} draft={draft} />}
          <ol className="grid gap-1">
            {sections.map((s, i) => (
              <li key={s.id}>
                <div className={`flex items-center rounded-lg ${sel === s.id ? "bg-[var(--haip-primary-tint)] font-semibold" : "hover:bg-[var(--haip-surface)]"}`}>
                  <button type="button" onClick={() => select(s.id)} className="min-h-11 min-w-0 flex-1 px-2 text-left text-sm">
                    <span className="block truncate">{SECTION_NAMES[s.type]?.[0] || s.type}</span>
                    {headingOf(s) && <span className="block truncate text-xs font-normal text-[var(--haip-fg-muted)]">{headingOf(s)}</span>}
                  </button>
                  <button type="button" aria-label={`More for ${SECTION_NAMES[s.type]?.[0] || s.type}`} aria-expanded={menuFor === s.id}
                    onClick={() => setMenuFor(m => (m === s.id ? null : s.id))} className="grid h-11 w-10 place-items-center rounded-lg"><MoreHorizontal size={18} /></button>
                </div>
                {menuFor === s.id && (
                  <div role="menu" className="mb-1 ml-3 grid rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-1 shadow-[var(--haip-shadow-lg)]">
                    <MenuItem icon={<Copy size={15} />} label="Copy" onClick={() => { let id: string | null = null; edit(d => { id = duplicateSection(d, target, i); }); select(id); }} />
                    <MenuItem icon={<ArrowUp size={15} />} label="Move up" disabled={i === 0} onClick={() => { edit(d => moveSection(d, target, i, -1)); setMenuFor(null); }} />
                    <MenuItem icon={<ArrowDown size={15} />} label="Move down" disabled={i === sections.length - 1} onClick={() => { edit(d => moveSection(d, target, i, 1)); setMenuFor(null); }} />
                    <MenuItem icon={<Trash2 size={15} />} label="Remove" danger disabled={sections.length === 1} onClick={() => { edit(d => removeSection(d, target, i)); select(null); }} />
                  </div>
                )}
              </li>
            ))}
          </ol>
          {adding && (
            <div role="dialog" aria-label="Add a part" className="absolute left-3 right-3 top-14 z-10 grid max-h-[70vh] gap-1 overflow-y-auto rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-2 shadow-[var(--haip-shadow-lg)]">
              {addable(target).map(t => (
                <button key={t} type="button" className="grid min-h-11 rounded-xl px-3 py-2 text-left hover:bg-[var(--haip-surface)]"
                  onClick={() => { let id: string | null = null; const at = sel ? sections.findIndex(s => s.id === sel) + 1 : undefined; edit(d => { id = addSection(d, target, t, at); }); setAdding(false); select(id); }}>
                  <b className="text-sm font-semibold">{SECTION_NAMES[t]?.[0] || t}</b><span className="text-xs text-[var(--haip-fg-muted)]">{SECTION_NAMES[t]?.[1]}</span></button>))}
            </div>
          )}
        </aside>

        <main className="min-w-0 flex-1">
          {liveData ? <Stage live={liveData} page={page} env={env} device={device} selected={sel} onSelect={select} />
            : <div className="h-full animate-pulse bg-[var(--haip-surface)]" />}
        </main>

        <aside aria-label="Change the selected part" className="w-[320px] shrink-0 overflow-y-auto border-l border-[var(--haip-border)] bg-[var(--haip-card)] p-4">
          {section ? (
            <SectionInspector key={section.id} s={section} media={media.data || []} mediaLoading={media.isLoading}
              onSlots={slots => edit(d => { const x = sectionsOf(d, target)?.find(y => y.id === section.id); if (x) x.slots = slots; })}
              onVariant={v => edit(d => { const x = sectionsOf(d, target)?.find(y => y.id === section.id); if (x) x.variant = v; })}
              onAskAi={target.kind === "page" ? () => setAiFor(section) : undefined} />
          ) : target.kind === "page" ? (
            <PageInspector page={page} onChange={p => edit(d => { const x = d.pages.find(y => y.slug === page.slug); if (x) Object.assign(x, p); })}
              onDelete={page.slug === "/" ? undefined : () => { if (window.confirm(`Delete the page "${page.title}"? You can undo this.`)) { edit(d => removePage(d, page.slug)); setTarget({ kind: "page", slug: "/" }); } }} />
          ) : <p className="text-sm text-[var(--haip-fg-muted)]">Click a part of the page to change it. This design is used for every {target.key === "stay" ? "stay" : "package"}.</p>}
        </aside>
      </div>
      <ChangeSheet open={!!aiFor} onClose={() => setAiFor(null)} onChanged={() => draft.load()}
        section={aiFor ? { id: aiFor.id, name: SECTION_NAMES[aiFor.type]?.[0] || aiFor.type } : undefined} />
    </div>
  );
}

/** Section types a person may add here: page types on pages; on a template also its own data parts (W4). */
function addable(t: Target): SectionType[] {
  const all = Object.keys(SECTION_NAMES) as SectionType[];
  return t.kind === "page" ? all.filter(x => !templateOf(x)) : [...all.filter(x => templateOf(x) === t.key), ...TEMPLATE_SHARED];
}

function MenuItem({ icon, label, onClick, disabled, danger }: { icon: ReactNode; label: string; onClick: () => void; disabled?: boolean; danger?: boolean }) {
  return <button type="button" role="menuitem" disabled={disabled} onClick={onClick}
    className={`flex min-h-10 items-center gap-2 rounded-lg px-2 text-left text-sm hover:bg-[var(--haip-surface)] disabled:opacity-40 ${danger ? "text-[var(--haip-status-danger-fg)]" : ""}`}>
    <span aria-hidden="true">{icon}</span>{label}</button>;
}

/** The real site at a device width, scaled to fit; a click selects the part under it instead of following links. */
function Stage({ live, page, env, device, selected, onSelect }: { live: LiveDataV2; page: PageV2; env: SiteEnv; device: Device; selected: string | null; onSelect: (id: string | null) => void }) {
  const stage = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [height, setHeight] = useState(0);
  const width = DEVICES[device];
  useLayoutEffect(() => {
    const el = stage.current;
    if (!el) return;
    const measure = () => setScale(Math.min(1, (el.clientWidth - 32) / width));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [width]);
  useEffect(() => {
    const el = inner.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setHeight(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (!selected || !stage.current) return;
    const node = stage.current.querySelector<HTMLElement>(`[id="${selected}"]`);
    if (node) stage.current.scrollTo({ top: Math.max(0, node.offsetTop * scale - 40), behavior: "smooth" });
  }, [selected, scale]);
  const onClick = (e: MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.closest("a, button, summary, form, input, select, textarea, label")) e.preventDefault();
    const sec = t.closest<HTMLElement>("[data-section]");
    onSelect(sec?.id || null);
  };
  return (
    <div ref={stage} className="v2-stage h-full overflow-auto bg-[var(--haip-surface)] p-4" aria-label="Page preview: click a part to change it">
      <style>{`.v2-stage [data-section]{cursor:pointer}.v2-stage [data-section]:hover{outline:2px dashed var(--haip-accent);outline-offset:-2px}${selected ? `.v2-stage [id="${selected}"]{outline:3px solid var(--haip-accent)!important;outline-offset:-3px}` : ""}`}</style>
      <div style={{ width: width * scale, height: height * scale, margin: "0 auto", position: "relative" } as CSSProperties}>
        <div ref={inner} onClickCapture={onClick} onSubmitCapture={e => e.preventDefault()}
          style={{ width, transform: `scale(${scale})`, transformOrigin: "0 0", position: "absolute", left: 0, top: 0 } as CSSProperties}
          className="overflow-hidden rounded-md bg-white shadow-[var(--haip-shadow-lg)]">
          <SiteRendererV2 live={live} page={page} env={env} />
        </div>
      </div>
    </div>
  );
}
