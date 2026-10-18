"use client";
import { useState } from "react";
// Typed form for one content payload. Mirrors backend/app/schemas/marketing.py (change both together).
import type { Kind } from "./types";
import { inputCls, btn } from "./types";

type P = Record<string, unknown>;
type Row = Record<string, string | undefined>;

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{label}</span>
      {children}
      {hint && <span className="block text-xs text-[var(--haip-fg-subtle)]">{hint}</span>}
    </label>
  );
}

export function emptyPayload(kind: Kind): P {
  switch (kind) {
    case "carousel": return { caption: "", hashtags: [], slides: [{}, {}] };
    case "story": return { frames: [{}] };
    case "promo": return { caption: "", hashtags: [], headline: "", body: "", cta: "DM us" };
    default: return { caption: "", hashtags: [] };
  }
}

function rows(v: unknown): Row[] {
  return Array.isArray(v) ? (v as Row[]) : [];
}

export function PayloadForm({ kind, value, onChange, disabled }: { kind: Kind; value: P; onChange: (p: P) => void; disabled?: boolean }) {
  const set = (k: string, v: unknown) => onChange({ ...value, [k]: v });
  const str = (k: string) => (typeof value[k] === "string" ? (value[k] as string) : "");
  // Raw text kept locally so a trailing space survives typing; the parent remounts this form per version (key).
  const [tags, setTags] = useState(Array.isArray(value.hashtags) ? (value.hashtags as string[]).join(" ") : "");
  const listKey = kind === "carousel" ? "slides" : kind === "story" ? "frames" : null;
  const list = listKey ? rows(value[listKey]) : [];
  const setRow = (i: number, k: string, v: string) => {
    if (!listKey) return;
    set(listKey, list.map((r, j) => (j === i ? { ...r, [k]: v || undefined } : r)));
  };
  const max = 10;
  const min = kind === "carousel" ? 2 : 1;
  const caption = str("caption");

  return (
    <fieldset disabled={disabled} className="space-y-4">
      {kind === "promo" && (
        <>
          <Field label="Headline"><input className={inputCls} maxLength={80} value={str("headline")} onChange={e => set("headline", e.target.value)} /></Field>
          <Field label="Body"><textarea className={inputCls} rows={3} maxLength={400} value={str("body")} onChange={e => set("body", e.target.value)} /></Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Call to action"><input className={inputCls} maxLength={40} value={str("cta")} onChange={e => set("cta", e.target.value)} /></Field>
            <Field label="Offer (optional)" hint="No prices or discounts if your workspace hands prices to staff.">
              <input className={inputCls} maxLength={160} value={str("offer")} onChange={e => set("offer", e.target.value || undefined)} />
            </Field>
          </div>
        </>
      )}

      {listKey && (
        <div className="space-y-3">
          {list.map((r, i) => (
            <div key={i} className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">{kind === "carousel" ? "Slide" : "Frame"} {i + 1}</span>
                {list.length > min && (
                  <button type="button" className="min-h-11 px-2 text-xs font-semibold text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)] sm:min-h-0"
                    onClick={() => set(listKey, list.filter((_, j) => j !== i))}>Remove</button>
                )}
              </div>
              {kind === "carousel" ? (
                <>
                  <input className={inputCls} placeholder="Headline" maxLength={80} value={r.headline ?? ""} onChange={e => setRow(i, "headline", e.target.value)} />
                  <textarea className={inputCls} placeholder="Body" rows={2} maxLength={200} value={r.body ?? ""} onChange={e => setRow(i, "body", e.target.value)} />
                </>
              ) : (
                <>
                  <input className={inputCls} placeholder="Text on the frame" maxLength={120} value={r.text ?? ""} onChange={e => setRow(i, "text", e.target.value)} />
                  <input className={inputCls} placeholder="Call to action (optional)" maxLength={40} value={r.cta ?? ""} onChange={e => setRow(i, "cta", e.target.value)} />
                </>
              )}
            </div>
          ))}
          {list.length < max && <button type="button" className={btn} onClick={() => set(listKey, [...list, {}])}>Add {kind === "carousel" ? "slide" : "frame"}</button>}
        </div>
      )}

      {kind !== "story" && (
        <>
          <Field label="Caption" hint={`${caption.length} / 2,200 characters`}>
            <textarea className={inputCls} rows={6} maxLength={2200} value={caption} onChange={e => set("caption", e.target.value)} />
          </Field>
          <Field label="Hashtags" hint="Separate with spaces. Up to 30.">
            <input className={inputCls} value={tags}
              onChange={e => { setTags(e.target.value); set("hashtags", e.target.value.split(/\s+/).filter(Boolean)); }} />
          </Field>
        </>
      )}
      {kind === "post" && (
        <Field label="Text on the image (optional)">
          <input className={inputCls} maxLength={120} value={str("overlay_text")} onChange={e => set("overlay_text", e.target.value || undefined)} />
        </Field>
      )}
    </fieldset>
  );
}
