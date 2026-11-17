"use client";
// Website W4 in the on-page editor: the stay and package page designs. A design is drawn with one real stay or package
// (picked at the top of the block list) so the owner sees exactly what guests get; "Make my own design" copies the
// standard design into the draft, after which every part can be changed like a page.
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { webApi } from "@/lib/website";
import type { Stay } from "@/site-blocks/types";
import { defaultTemplate, type LiveDataV2, type PageV2, type SpecV2 } from "@/site-blocks/v2/types";
import { newSectionId, type TemplateKey, type Target } from "./targets";
import type { Draft } from "../useDraft";

export const TEMPLATE_TYPES: TemplateKey[] = ["stay", "package"];
export const templateLabel = (k: TemplateKey) => (k === "stay" ? "Stay page design" : "Package page design");

export function templatePage(doc: SpecV2, key: TemplateKey): PageV2 {
  return { slug: key === "stay" ? "/stays" : "/packages", title: templateLabel(key), nav: false, seo: { title: "", description: "" },
    sections: doc.templates?.[key]?.sections || defaultTemplate(key) };
}

/** Copies the standard design into the draft with site-unique ids (they name the WhatsApp reference codes). */
export function startTemplate(doc: SpecV2, key: TemplateKey): void {
  const sections = defaultTemplate(key).map(s => ({ ...s, id: "" }));
  doc.templates = { ...(doc.templates || {}), [key]: { sections: [] } };
  for (const s of sections) doc.templates[key]!.sections.push({ ...s, id: newSectionId(doc, s.type) });
}

export interface TemplatePreview { stay: Stay | null; packageKey: string | null; options: [string, string][]; chosen: string; choose: (v: string) => void;
  loading: boolean; failed: boolean; retry: () => void }

export function useTemplatePreview(target: Target, live: LiveDataV2 | undefined): TemplatePreview {
  const key = target.kind === "template" ? target.key : null;
  const options: [string, string][] = key === "stay" ? (live?.stays_index || []).filter(s => s.slug).map(s => [s.slug as string, s.name])
    : key === "package" ? (live?.packages_index || []).map(p => [p.key, p.name]) : [];
  const [chosen, setChosen] = useState("");
  useEffect(() => { if (options.length && !options.some(([v]) => v === chosen)) setChosen(options[0][0]); }, [options, chosen]);
  const stay = useQuery({ queryKey: ["web-stay-preview", chosen], queryFn: () => webApi.stayPreview(chosen), enabled: key === "stay" && !!chosen, staleTime: 5 * 60 * 1000 });
  return { stay: key === "stay" ? stay.data || null : null, packageKey: key === "package" ? chosen || null : null, options, chosen, choose: setChosen,
    loading: key === "stay" && stay.isLoading, failed: key === "stay" && stay.isError, retry: () => { stay.refetch(); } };
}

export function TemplateBar({ target, tpl, draft }: { target: Extract<Target, { kind: "template" }>; tpl: TemplatePreview; draft: Draft }) {
  const doc = draft.doc as unknown as SpecV2 | null;
  const own = !!doc?.templates?.[target.key];
  const what = target.key === "stay" ? "stay" : "package";
  return (
    <div className="mb-2 grid gap-2 rounded-xl bg-[var(--haip-surface)] p-3 text-sm">
      {tpl.options.length ? (
        <label className="grid gap-1"><span className="text-xs font-semibold">Show it with</span>
          <select className={`${inputCls} min-h-10`} value={tpl.chosen} onChange={e => tpl.choose(e.target.value)}>
            {tpl.options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      ) : <p className="text-[var(--haip-fg-muted)]">{target.key === "stay" ? "Add a stay in Properties to see this design." : "Publish a package to see this design."}</p>}
      {tpl.loading && <p className="text-xs" role="status">Loading this {what}…</p>}
      {tpl.failed && <p className="text-xs font-semibold" role="alert">Couldn&apos;t load this {what}. <button type="button" className="underline" onClick={tpl.retry}>Try again</button></p>}
      <p className="text-xs text-[var(--haip-fg-muted)]">One design for every {what}: each gets its own page with its own photos, details and price.
        {target.key === "package" ? " Pages are at /packages/<name>." : " Pages are at /stays/<name>."}</p>
      {!own && <button type="button" className={btnPrimary} onClick={() => draft.update(d => startTemplate(d as unknown as SpecV2, target.key))}>Make my own design</button>}
    </div>
  );
}
