"use client";
// Edits one section's fields, generated from the shared spec (site-blocks/blocks.json), plus layout and background.
// Used by the AI view's side panel and the phone sheet; the Builder view uses Puck's own fields with the same spec.
import { useState } from "react";
import { ArrowDown, ArrowUp, Copy, ImagePlus, Trash2, X } from "lucide-react";
import { StatusPill } from "@/components/ui/kit";
import { inputCls } from "@/components/marketing/studio/types";
import { SPEC, type Block, type FieldSpec } from "@/site-blocks/types";
import type { MediaItem } from "@/lib/website";

const label = "text-[13px] font-semibold text-[var(--haip-fg)]";
const pill = (on: boolean) =>
  `min-h-9 rounded-full border px-3 text-[13px] font-semibold ${on ? "border-[var(--primary)] bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]"}`;
const LAYOUT_LABEL: Record<string, string> = { split: "Split", full: "Full photo", centred: "Centred", cards: "Cards", list: "List",
  image_left: "Photo left", image_right: "Photo right", grid: "Grid", single: "Single", mosaic: "Mosaic", left: "Left" };
const BG_LABEL: Record<string, string> = { page: "Page", soft: "Soft tint", brand: "Brand colour" };

function options(f: FieldSpec): string[] {
  if (f.options) return f.options;
  const from = (SPEC as unknown as Record<string, unknown>)[f.options_from || ""];
  return Array.isArray(from) ? (from as string[]) : [];
}

export function PhotoThumb({ refValue, media, onPick, onClear }: { refValue: string; media: MediaItem[]; onPick: () => void; onClear: () => void }) {
  const m = media.find(x => x.ref === refValue);
  return (
    <div className="flex items-center gap-2">
      {m?.url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={m.url} alt={m.alt_text || ""} className="h-14 w-20 rounded-lg object-cover" />
      ) : <div className="grid h-14 w-20 place-items-center rounded-lg bg-[var(--haip-surface)] text-[11px] text-[var(--haip-fg-subtle)]">{refValue ? "Missing" : "No photo"}</div>}
      <button type="button" className={pill(false)} onClick={onPick}><ImagePlus className="mr-1 inline h-4 w-4" aria-hidden="true" />{refValue ? "Change" : "Choose"}</button>
      {refValue && <button type="button" className={pill(false)} onClick={onClear} aria-label="Remove photo"><X className="h-4 w-4" aria-hidden="true" /></button>}
    </div>
  );
}

function Field({ f, value, onChange, media, pickPhoto }: {
  f: FieldSpec; value: unknown; onChange: (v: unknown) => void; media: MediaItem[]; pickPhoto: (cb: (ref: string) => void) => void;
}) {
  const s = typeof value === "string" ? value : "";
  const count = f.max && (f.kind === "text" || f.kind === "textarea") ? <span className={`justify-self-end text-xs ${s.length > f.max ? "font-semibold text-[var(--haip-status-warning-fg)]" : "text-[var(--haip-fg-subtle)]"}`}>{s.length} / {f.max}</span> : null;
  switch (f.kind) {
    case "text": case "link":
      return <label className="grid gap-1"><span className={label}>{f.label}</span>
        <input className={inputCls} value={s} maxLength={f.kind === "link" ? 500 : f.max} placeholder={f.kind === "link" ? "/book, /contact, wa: or https://…" : undefined} onChange={e => onChange(e.target.value)} />{count}</label>;
    case "date":
      return <label className="grid gap-1"><span className={label}>{f.label}</span><input type="date" className={inputCls} value={s} onChange={e => onChange(e.target.value)} /></label>;
    case "textarea":
      return <label className="grid gap-1"><span className={label}>{f.label}</span><textarea className={inputCls} rows={4} value={s} maxLength={f.max} onChange={e => onChange(e.target.value)} />{count}</label>;
    case "lines": {
      const list = Array.isArray(value) ? (value as string[]) : [];
      return <label className="grid gap-1"><span className={label}>{f.label}</span>
        <textarea className={inputCls} rows={Math.max(3, list.length + 1)} value={list.join("\n")} onChange={e => onChange(e.target.value.split("\n").slice(0, f.max_items || 10))} />
        <span className="text-xs text-[var(--haip-fg-subtle)]">Up to {f.max_items} lines</span></label>;
    }
    case "toggle":
      return <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={value === true} onChange={e => onChange(e.target.checked)} />{f.label}</label>;
    case "select":
      return <div className="grid gap-1"><span className={label}>{f.label}</span><div className="flex flex-wrap gap-1.5">
        {options(f).map(o => <button key={o} type="button" className={pill(value === o)} aria-pressed={value === o} onClick={() => onChange(o)}>{o === "all" ? "All" : o[0].toUpperCase() + o.slice(1)}</button>)}</div></div>;
    case "tags": {
      const set = Array.isArray(value) ? (value as string[]) : [];
      return <div className="grid gap-1"><span className={label}>{f.label}</span><div className="flex flex-wrap gap-1.5">
        {options(f).map(o => { const on = set.includes(o); return <button key={o} type="button" className={pill(on)} aria-pressed={on} onClick={() => onChange(on ? set.filter(x => x !== o) : [...set, o])}>{o}</button>; })}</div></div>;
    }
    case "image":
      return <div className="grid gap-1"><span className={label}>{f.label}</span><PhotoThumb refValue={s} media={media} onPick={() => pickPhoto(ref => onChange(ref))} onClear={() => onChange("")} /></div>;
    case "images": {
      const list = Array.isArray(value) ? (value as string[]) : [];
      return <div className="grid gap-2"><span className={label}>{f.label}</span>
        <div className="grid grid-cols-4 gap-1.5">{list.map((r, i) => { const m = media.find(x => x.ref === r); return (
          <div key={r} className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {m?.url ? <img src={m.url} alt="" className="aspect-square w-full rounded-lg object-cover" /> : <div className="aspect-square rounded-lg bg-[var(--haip-surface)]" />}
            <button type="button" aria-label="Remove" className="absolute right-1 top-1 grid h-7 w-7 place-items-center rounded-full bg-[var(--haip-card)] shadow" onClick={() => onChange(list.filter((_, j) => j !== i))}><X className="h-3.5 w-3.5" aria-hidden="true" /></button>
          </div>); })}</div>
        {list.length < (f.max_items || 12) && <button type="button" className={pill(false)} onClick={() => pickPhoto(ref => onChange(list.includes(ref) ? list : [...list, ref]))}><ImagePlus className="mr-1 inline h-4 w-4" aria-hidden="true" />Add photo</button>}</div>;
    }
    case "list": {
      const rows = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
      const set = (i: number, k: string, v: unknown) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
      return <div className="grid gap-2"><span className={label}>{f.label}</span>
        {rows.map((r, i) => (
          <div key={i} className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3">
            {(f.item || []).map(sub => <Field key={sub.key} f={sub} value={r[sub.key]} onChange={v => set(i, sub.key, v)} media={media} pickPhoto={pickPhoto} />)}
            <div className="flex gap-1.5">
              <button type="button" className={pill(false)} disabled={i === 0} onClick={() => { const n = [...rows]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; onChange(n); }} aria-label="Move up"><ArrowUp className="h-4 w-4" aria-hidden="true" /></button>
              <button type="button" className={pill(false)} onClick={() => onChange(rows.filter((_, j) => j !== i))}>Remove</button>
            </div>
          </div>
        ))}
        {rows.length < (f.max_items || 10) && <button type="button" className={pill(false)} onClick={() => onChange([...rows, Object.fromEntries((f.item || []).map(x => [x.key, x.kind === "select" ? options(x)[0] : ""]))])}>Add</button>}
      </div>;
    }
  }
}

export function FieldPanel({ block, onChange, onMove, onDuplicate, onDelete, media, pickPhoto, compact }: {
  block: Block; onChange: (props: Block["props"]) => void; onMove?: (dir: -1 | 1) => void; onDuplicate?: () => void; onDelete?: () => void;
  media: MediaItem[]; pickPhoto: (cb: (ref: string) => void) => void; compact?: boolean;
}) {
  const spec = SPEC.blocks[block.type];
  const [tab, setTab] = useState<"content" | "design">("content");
  if (!spec) return <p className="text-sm">Unknown section.</p>;
  const set = (k: string, v: unknown) => onChange({ ...block.props, [k]: v });
  return (
    <div className="grid gap-3">
      {!compact && <div className="flex items-center justify-between gap-2"><h3 className="font-[family-name:var(--font-display)] text-lg font-bold">{spec.label}</h3>{spec.system && <StatusPill tone="neutral">Built by HAIP</StatusPill>}</div>}
      {spec.live && <div className="rounded-xl bg-[var(--haip-status-info-bg)] px-3 py-2.5 text-[13px] leading-snug text-[var(--haip-status-info-fg)]"><b className="block">Live from HAIP</b>{spec.live}</div>}
      <div className="flex gap-1 rounded-full bg-[var(--haip-surface)] p-1" role="tablist" aria-label="Section settings">
        {(["content", "design"] as const).map(t => <button key={t} role="tab" aria-selected={tab === t} type="button" onClick={() => setTab(t)}
          className={`min-h-8 flex-1 rounded-full text-[13px] font-semibold ${tab === t ? "bg-[var(--haip-card)] shadow-sm" : "text-[var(--haip-fg-muted)]"}`}>{t === "content" ? "Content" : "Design"}</button>)}
      </div>
      {tab === "content" ? spec.fields.map(f => <Field key={f.key} f={f} value={block.props[f.key]} onChange={v => set(f.key, v)} media={media} pickPhoto={pickPhoto} />) : (
        <>
          {spec.layouts && spec.layouts.length > 1 ? <div className="grid gap-1"><span className={label}>Layout</span><div className="flex flex-wrap gap-1.5">
            {spec.layouts.map(l => <button key={l} type="button" className={pill(block.props.layout === l)} aria-pressed={block.props.layout === l} onClick={() => set("layout", l)}>{LAYOUT_LABEL[l] || l}</button>)}</div></div>
            : <p className="text-[13px] text-[var(--haip-fg-subtle)]">This section has one layout.</p>}
          <div className="grid gap-1"><span className={label}>Background</span><div className="flex flex-wrap gap-1.5">
            {SPEC.backgrounds.map(b => <button key={b} type="button" className={pill((block.props.background || "page") === b)} onClick={() => set("background", b)}>{BG_LABEL[b] || b}</button>)}</div></div>
        </>
      )}
      {!spec.system && (onMove || onDelete) && (
        <div className="flex flex-wrap gap-1.5 border-t border-[var(--haip-border)] pt-3">
          {onMove && <><button type="button" className={pill(false)} onClick={() => onMove(-1)} aria-label="Move up"><ArrowUp className="h-4 w-4" aria-hidden="true" /></button>
            <button type="button" className={pill(false)} onClick={() => onMove(1)} aria-label="Move down"><ArrowDown className="h-4 w-4" aria-hidden="true" /></button></>}
          {onDuplicate && <button type="button" className={pill(false)} onClick={onDuplicate}><Copy className="mr-1 inline h-4 w-4" aria-hidden="true" />Duplicate</button>}
          {onDelete && <button type="button" className={pill(false)} onClick={onDelete}><Trash2 className="mr-1 inline h-4 w-4" aria-hidden="true" />Delete</button>}
        </div>
      )}
    </div>
  );
}
