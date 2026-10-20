"use client";
// Phone quick edit: the page at phone width, quick chips for what owners change most, and a bottom sheet with the
// tapped section's fields. Adding pages and deep layout changes are left to a laptop.
import { useState } from "react";
import { Sparkles } from "lucide-react";
import { ActionSheet } from "@/components/bookings/ActionSheet";
import type { MediaItem } from "@/lib/website";
import type { LiveData, Page, SiteEnv } from "@/site-blocks/types";
import { AiChat } from "./AiChat";
import { Canvas } from "./Canvas";
import { addBlock, removeBlock, setProps } from "./docOps";
import { FieldPanel } from "./FieldPanel";
import { PagePanel, SitePanel } from "./PagePanel";
import type { Draft } from "./useDraft";

const QUICK: { type: string; label: string }[] = [
  { type: "Offer", label: "Offer banner" }, { type: "Hero", label: "Hero photo" }, { type: "Reviews", label: "Reviews" }, { type: "Contact", label: "Contact" },
];

export function PhoneEditor({ draft, page, live, env, media, pickPhoto, selected, setSelected, touched }: {
  draft: Draft; page: Page; live: LiveData; env: SiteEnv; media: MediaItem[]; pickPhoto: (cb: (ref: string) => void) => void;
  setPageId: (id: string) => void; selected: string | null; setSelected: (id: string) => void; touched: Set<string>;
}) {
  const [sheet, setSheet] = useState<"none" | "section" | "ai" | "page" | "site">("none");
  const block = page.content.find(b => b.props.id === selected);
  const quick = (type: string) => {
    let target = page.content.find(b => b.type === type)?.props.id;
    if (!target && type === "Offer") draft.update(d => { target = addBlock(d, page.id, "Offer", page.content[0]?.props.id); });
    if (target) { setSelected(target); setSheet("section"); }
  };
  const chip = "min-h-9 shrink-0 rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[13px] font-semibold";
  return (
    <div className="grid gap-0">
      <div className="flex gap-1.5 overflow-x-auto border-b border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2">
        <button type="button" className={`${chip} border-[var(--primary)] text-[var(--primary)]`} onClick={() => setSheet("ai")}><Sparkles className="mr-1 inline h-4 w-4" aria-hidden="true" />Ask AI</button>
        {QUICK.map(q => <button key={q.type} type="button" className={chip} onClick={() => quick(q.type)}>{q.label}</button>)}
        <button type="button" className={chip} onClick={() => setSheet("page")}>Search preview</button>
        <button type="button" className={chip} onClick={() => setSheet("site")}>Contact &amp; look</button>
      </div>
      <div className="h-[calc(100dvh-52px-60px-110px)] min-h-[420px]">
        <Canvas live={live} page={page} env={env} device="phone" selectedId={selected} flash={touched} onSelect={id => { setSelected(id); setSheet("section"); }} />
      </div>
      <ActionSheet open={sheet !== "none"} onClose={() => setSheet("none")}
        title={sheet === "ai" ? "Ask the AI developer" : sheet === "page" ? "Search preview" : sheet === "site" ? "Contact and look" : block ? "Edit section" : ""}>
        <div className="max-h-[70dvh] overflow-y-auto">
          {sheet === "section" && block && <FieldPanel block={block} media={media} pickPhoto={pickPhoto}
            onChange={props => draft.update(d => setProps(d, page.id, block.props.id, props))}
            onDelete={() => { draft.update(d => removeBlock(d, page.id, block.props.id)); setSheet("none"); }} />}
          {sheet === "ai" && <div className="h-[60dvh]"><AiChat draft={draft} onTouched={() => setSheet("none")} /></div>}
          {sheet === "page" && draft.doc && <PagePanel doc={draft.doc} page={page} host={""} update={draft.update} />}
          {sheet === "site" && draft.doc && <SitePanel doc={draft.doc} update={draft.update} />}
        </div>
      </ActionSheet>
    </div>
  );
}
