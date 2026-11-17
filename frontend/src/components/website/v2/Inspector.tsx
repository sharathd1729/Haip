"use client";
// The right-hand panel of the on-page editor (website W2): the words, layout and photo of the selected section, or the
// page's own settings when nothing is selected. Every change goes straight into the draft (useDraft autosaves it); the
// server refuses typed prices and unreadable values and the reason shows in the editor's save bar.
import { useState, type ReactNode } from "react";
import { Sparkles, Trash2 } from "lucide-react";
import { inputCls, btn } from "@/components/marketing/studio/types";
import type { MediaItem } from "@/lib/website";
import { CATALOGUE, type PageV2, type SectionV2 } from "@/site-blocks/v2/types";
import { FIELD, FIELDS, SECTION_NAMES } from "../DirectEditors";
import { PhotoPicker } from "../PhotoPicker";

const human = (v: string) => v.replace(/-/g, " ").replace(/^./, c => c.toUpperCase());
/** Sections with a photo slot a person picks (others bind their photos from HAIP). */
const PHOTO_SLOT: Partial<Record<string, string>> = { hero: "media", text: "media" };

export function SectionInspector({ s, media, mediaLoading, onSlots, onVariant, onAskAi, extra }: {
  s: SectionV2; media: MediaItem[]; mediaLoading: boolean; onSlots: (slots: Record<string, unknown>) => void;
  onVariant: (v: string) => void; onAskAi?: () => void; extra?: ReactNode;
}) {
  const [picking, setPicking] = useState(false);
  const sec = CATALOGUE.sections[s.type];
  const photoKey = PHOTO_SLOT[s.type];
  const photo = photoKey && typeof s.slots[photoKey] === "string" ? media.find(m => m.ref === s.slots[photoKey]) : undefined;
  const fields = FIELDS[s.type] || [];
  return (
    <div className="grid gap-4">
      <div>
        <p className="font-display text-lg font-semibold">{SECTION_NAMES[s.type]?.[0] || sec?.label || s.type}</p>
        <p className="text-sm text-[var(--haip-fg-muted)]">{SECTION_NAMES[s.type]?.[1] || ""}</p>
      </div>
      {sec && sec.variants.length > 1 && (
        <fieldset className="grid gap-2"><legend className="mb-1 text-sm font-semibold">Layout</legend>
          <div className="flex flex-wrap gap-2">{sec.variants.map(v => (
            <button key={v} type="button" aria-pressed={s.variant === v} onClick={() => onVariant(v)}
              className={`min-h-11 rounded-xl border px-3 text-sm ${s.variant === v ? "border-[var(--primary)] bg-[var(--haip-primary-tint)] font-semibold" : "border-[var(--haip-border)]"}`}>{human(v)}</button>))}
          </div></fieldset>
      )}
      {fields.map(k => {
        const [label, max, hint] = FIELD[k];
        const value = String(s.slots[k] ?? "");
        return (
          <label key={k} className="grid gap-1"><span className="text-sm font-semibold">{label}</span>
            {max > 90 ? <textarea className={`${inputCls} min-h-24`} rows={k === "body" ? 7 : 3} maxLength={max} value={value} onChange={e => onSlots({ ...s.slots, [k]: e.target.value })} />
              : <input className={inputCls} maxLength={max} value={value} onChange={e => onSlots({ ...s.slots, [k]: e.target.value })} />}
            <span className="text-xs text-[var(--haip-fg-muted)]">{hint ? `${hint} ` : ""}{value.length} / {max}</span></label>
        );
      })}
      {photoKey && (s.type !== "text" || s.variant === "with-photo") && (
        <div className="grid gap-2"><span className="text-sm font-semibold">Photo</span>
          <div className="flex items-center gap-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {photo?.url ? <img src={photo.url} alt="" className="h-14 w-20 rounded-lg object-cover" /> : <span className="grid h-14 w-20 place-items-center rounded-lg bg-[var(--haip-surface)] text-xs text-[var(--haip-fg-muted)]">{s.slots[photoKey] ? "Chosen" : "Auto"}</span>}
            <button type="button" className={btn} onClick={() => setPicking(true)}>{s.slots[photoKey] ? "Change" : "Choose"}</button>
            {!!s.slots[photoKey] && <button type="button" className="min-h-11 text-sm font-semibold text-[var(--primary)]" onClick={() => onSlots({ ...s.slots, [photoKey]: null })}>Use auto</button>}
          </div>
          {!s.slots[photoKey] && s.type === "hero" && <span className="text-xs text-[var(--haip-fg-muted)]">Auto = your newest approved photo.</span>}
        </div>
      )}
      {!fields.length && <p className="text-sm text-[var(--haip-fg-muted)]">This part fills itself from your HAIP data.</p>}
      {extra}
      {onAskAi && (
        <button type="button" onClick={onAskAi} className="flex min-h-11 items-center gap-2 border-t border-[var(--haip-border)] pt-3 text-left text-sm font-semibold text-[var(--primary)]">
          <Sparkles size={16} aria-hidden="true" />Ask AI to change this part <span className="font-normal text-[var(--haip-fg-muted)]">(optional)</span></button>
      )}
      <p className="text-xs text-[var(--haip-fg-muted)]">Prices can&apos;t be typed: HAIP shows your live prices by itself.</p>
      {photoKey && <PhotoPicker open={picking} onClose={() => setPicking(false)} media={media} loading={mediaLoading}
        selected={typeof s.slots[photoKey] === "string" ? (s.slots[photoKey] as string) : null} onPick={ref => onSlots({ ...s.slots, [photoKey]: ref })} />}
    </div>
  );
}

export function PageInspector({ page, onChange, onDelete }: { page: PageV2; onChange: (p: Partial<PageV2>) => void; onDelete?: () => void }) {
  const seo = page.seo;
  return (
    <div className="grid gap-4">
      <div><p className="font-display text-lg font-semibold">Page settings</p>
        <p className="text-sm text-[var(--haip-fg-muted)]">Click a part of the page to change it.</p></div>
      <label className="grid gap-1"><span className="text-sm font-semibold">Page name</span>
        <input className={inputCls} maxLength={60} value={page.title} onChange={e => onChange({ title: e.target.value })} /></label>
      <p className="text-sm"><span className="font-semibold">Address</span> <span className="text-[var(--haip-fg-muted)]">{page.slug}</span></p>
      {page.slug !== "/" && (
        <label className="flex min-h-11 items-center gap-3">
          <input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={page.nav} onChange={e => onChange({ nav: e.target.checked })} />
          <span className="text-sm font-semibold">List it in the menu <span className="block font-normal text-[var(--haip-fg-muted)]">Used when you haven&apos;t set your own menu.</span></span>
        </label>
      )}
      <label className="grid gap-1"><span className="text-sm font-semibold">Title in Google</span>
        <input className={inputCls} maxLength={70} value={seo.title} onChange={e => onChange({ seo: { ...seo, title: e.target.value } })} />
        <span className="text-xs text-[var(--haip-fg-muted)]">{seo.title.length} / 70</span></label>
      <label className="grid gap-1"><span className="text-sm font-semibold">Description in Google</span>
        <textarea className={`${inputCls} min-h-24`} maxLength={170} value={seo.description} onChange={e => onChange({ seo: { ...seo, description: e.target.value } })} />
        <span className="text-xs text-[var(--haip-fg-muted)]">{seo.description.length} / 170 · best 50 to 160</span></label>
      {onDelete && <button type="button" className={`${btn} justify-self-start`} onClick={onDelete}><Trash2 size={16} aria-hidden="true" />Delete this page</button>}
    </div>
  );
}
