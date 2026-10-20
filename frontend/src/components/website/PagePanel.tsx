"use client";
// Page settings (name, menu, search preview) and site-wide details (name, tagline, contact, theme) for the editor.
import { inputCls } from "@/components/marketing/studio/types";
import { PACKS, PERSONALITIES } from "@/site-blocks/packs";
import { SPEC, type Page, type SiteDoc } from "@/site-blocks/types";

const label = "text-[13px] font-semibold text-[var(--haip-fg)]";

function Counter({ n, lo, hi }: { n: number; lo: number; hi: number }) {
  const bad = n < lo || n > hi;
  return <span className={`justify-self-end text-xs ${bad ? "font-semibold text-[var(--haip-status-warning-fg)]" : "text-[var(--haip-fg-subtle)]"}`}>{n} / {hi}</span>;
}

export function PagePanel({ doc, page, host, update }: { doc: SiteDoc; page: Page; host: string; update: (fn: (d: SiteDoc) => void) => void }) {
  const fixed = !!SPEC.system_pages[page.key];
  const setPage = (fn: (p: Page) => void) => update(d => { const p = d.pages.find(x => x.id === page.id); if (p) fn(p); });
  return (
    <div className="grid gap-3">
      <h3 className="font-[family-name:var(--font-display)] text-lg font-bold">Page settings</h3>
      <p className="text-[13px] text-[var(--haip-fg-subtle)]">Tap a section on the page to edit it.</p>
      <label className="grid gap-1"><span className={label}>Page name</span>
        <input className={inputCls} value={page.title} maxLength={60} disabled={page.key === "home"} onChange={e => setPage(p => { p.title = e.target.value; })} /></label>
      <label className="grid gap-1"><span className={label}>Web address</span>
        <input className={inputCls} value={page.path} disabled={fixed} onChange={e => setPage(p => { p.path = "/" + e.target.value.toLowerCase().replace(/[^a-z0-9/-]+/g, "-").replace(/^\/+/, ""); })} /></label>
      {page.key !== "home" && page.key !== "stay" && <label className="flex min-h-11 items-center gap-3 text-sm">
        <input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={page.nav} onChange={e => setPage(p => { p.nav = e.target.checked; })} />Show in the top menu</label>}
      <div className="border-t border-[var(--haip-border)] pt-3 text-sm font-semibold">Search preview (Google)</div>
      <label className="grid gap-1"><span className={label}>Search title</span>
        <input className={inputCls} value={page.seo.title} maxLength={70} onChange={e => setPage(p => { p.seo.title = e.target.value; })} /><Counter n={page.seo.title.length} lo={1} hi={60} /></label>
      <label className="grid gap-1"><span className={label}>Description</span>
        <textarea className={inputCls} rows={3} maxLength={170} value={page.seo.description} onChange={e => setPage(p => { p.seo.description = e.target.value; })} /><Counter n={page.seo.description.length} lo={50} hi={160} /></label>
      <div className="rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-3">
        <div className="truncate text-xs text-[var(--haip-status-success-fg)]">{host}{page.path === "/" ? "" : page.path}</div>
        <div className="mt-0.5 text-base leading-snug text-[var(--haip-status-info-fg)]">{page.seo.title || page.title}</div>
        <div className="mt-0.5 text-[13px] text-[var(--haip-fg-muted)]">{page.seo.description || "No description yet. Google will pick text from the page."}</div>
      </div>
    </div>
  );
}

export function SitePanel({ doc, update }: { doc: SiteDoc; update: (fn: (d: SiteDoc) => void) => void }) {
  const c = doc.site.contact;
  const setContact = (k: keyof typeof c, v: string) => update(d => { d.site.contact[k] = v; });
  return (
    <div className="grid gap-3">
      <h3 className="font-[family-name:var(--font-display)] text-lg font-bold">Site details</h3>
      <label className="grid gap-1"><span className={label}>Business name</span><input className={inputCls} value={doc.site.name} maxLength={80} onChange={e => update(d => { d.site.name = e.target.value; })} /></label>
      <label className="grid gap-1"><span className={label}>Tagline</span><input className={inputCls} value={doc.site.tagline} maxLength={120} onChange={e => update(d => { d.site.tagline = e.target.value; })} /></label>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="grid gap-1"><span className={label}>Phone</span><input className={inputCls} inputMode="tel" value={c.phone} onChange={e => setContact("phone", e.target.value)} /></label>
        <label className="grid gap-1"><span className={label}>WhatsApp</span><input className={inputCls} inputMode="tel" value={c.whatsapp} onChange={e => setContact("whatsapp", e.target.value)} /></label>
      </div>
      <label className="grid gap-1"><span className={label}>Email</span><input className={inputCls} type="email" value={c.email} onChange={e => setContact("email", e.target.value)} /></label>
      <label className="grid gap-1"><span className={label}>Address</span><textarea className={inputCls} rows={2} value={c.address} onChange={e => setContact("address", e.target.value)} /></label>
      <div className="border-t border-[var(--haip-border)] pt-3 text-sm font-semibold">Look and feel</div>
      <ThemePicker doc={doc} update={update} />
    </div>
  );
}

export function ThemePicker({ doc, update }: { doc: SiteDoc; update: (fn: (d: SiteDoc) => void) => void }) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {Object.values(PACKS).map(p => {
          const on = doc.theme.pack === p.key;
          return (
            <button key={p.key} type="button" aria-pressed={on} onClick={() => update(d => { d.theme.pack = p.key; })}
              className={`grid gap-1.5 rounded-xl border p-2 text-left ${on ? "border-[var(--primary)] ring-2 ring-[var(--haip-primary-tint)]" : "border-[var(--haip-border)]"} bg-[var(--haip-card)]`}>
              <span className="flex h-5 overflow-hidden rounded-md" aria-hidden="true">{[p.bg, p.a, p.b, p.ink].map(c => <i key={c} className="flex-1" style={{ background: c }} />)}</span>
              <b className="text-[13px]">{p.name}</b><span className="text-[11.5px] text-[var(--haip-fg-subtle)]">{p.note}</span>
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(PERSONALITIES).map(([k, v]) => {
          const on = doc.theme.personality === k;
          return <button key={k} type="button" aria-pressed={on} onClick={() => update(d => { d.theme.personality = k; })}
            className={`min-h-9 rounded-full border px-3 text-[13px] font-semibold ${on ? "border-[var(--primary)] bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)]"}`}>{v}</button>;
        })}
      </div>
    </div>
  );
}
