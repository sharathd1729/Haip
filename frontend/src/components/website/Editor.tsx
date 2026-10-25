"use client";
// The website editor. Desktop: "AI developer" view (chat + live page; click a section to edit its fields) and
// "Builder" view (Puck). Phones get PhoneEditor (quick edits in a sheet). All views edit one draft (useDraft).
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Eye, Plus, Redo2, Undo2 } from "lucide-react";
import { StatusPill } from "@/components/ui/kit";
import { btn, btnPrimary } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webApi, webError, type SiteOut } from "@/lib/website";
import { SPEC, type LiveData, type SiteEnv } from "@/site-blocks/types";
import { AiChat } from "./AiChat";
import { Canvas, type Device } from "./Canvas";
import { ADDABLE, addBlock, addPage, duplicateBlock, moveBlock, pageOf, removeBlock, setProps } from "./docOps";
import { FieldPanel } from "./FieldPanel";
import { PagePanel, SitePanel } from "./PagePanel";
import { PhoneEditor } from "./PhoneEditor";
import { PhotoPicker } from "./PhotoPicker";
import { PuckBuilder } from "./PuckBuilder";
import { useDraft, type SaveState } from "./useDraft";

export const SAVE_LABEL: Record<SaveState, string> = { idle: "All changes saved", saving: "Saving…", saved: "Saved", conflict: "Changed elsewhere", error: "Not saved" };

export function useIsPhone() {
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const on = () => setPhone(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return phone;
}

export function Editor({ site, role, initialPage }: { site: SiteOut; role: string; initialPage?: string | null }) {
  const draft = useDraft();
  const qc = useQueryClient();
  const { toast } = useToast();
  const phone = useIsPhone();
  const live = useQuery({ queryKey: ["web-live"], queryFn: webApi.live });
  const media = useQuery({ queryKey: ["web-media"], queryFn: webApi.media });
  const [pageId, setPageId] = useState(initialPage || "home");
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<"chat" | "page" | "site" | "add">("chat");
  const [mode, setMode] = useState<"ai" | "builder">("ai");
  const [device, setDevice] = useState<Device>("desktop");
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [picker, setPicker] = useState<((ref: string) => void) | null>(null);
  const canPublish = role === "owner";
  const canApprove = role === "owner" || role === "manager";

  // A v2 (new builder) draft is a SiteSpec, not a block document: this editor can't show it; preview it instead.
  const isSpecV2 = (draft.doc as unknown as { spec_version?: number } | null)?.spec_version === 2;
  const doc = isSpecV2 ? null : draft.doc;
  const page = doc ? pageOf(doc, pageId) || doc.pages[0] : undefined;
  const block = page?.content.find(b => b.props.id === selected);
  const mediaList = useMemo(() => media.data || [], [media.data]);
  const env = useMemo<SiteEnv>(() => ({
    mode: "editor", base: "", apiBase: null, query: {},
    assets: Object.fromEntries(mediaList.filter(m => m.url).map(m => [m.id, { src: m.url as string, alt: m.alt_text || "" }])),
    stay: live.data?.stays?.[0] ?? null,   // a new-builder (v2) site has no stays list
  }), [mediaList, live.data]);
  const liveData = useMemo<LiveData | null>(() => (live.data && doc ? { ...live.data, doc } : null), [live.data, doc]);
  const pickPhoto = useCallback((cb: (ref: string) => void) => setPicker(() => cb), []);

  const select = (id: string) => { setSelected(id); setPanel("chat"); };
  const submit = useMutation({
    mutationFn: async () => { await draft.flush(); const v = draft.version!; return canPublish ? webApi.publish(v.id) : webApi.submit(v.id); },
    onSuccess: s => {
      qc.setQueryData(["web-site"], s);
      draft.load();
      toast({ variant: "success", title: canPublish ? "Published" : "Sent for approval", description: canPublish ? `Live at ${s.url}` : "An owner or manager approves it from the Website page." });
    },
    onError: e => toast({ variant: "error", title: canPublish ? "Not published" : "Not sent", description: webError(e, "Try again.") }),
  });
  const preview = async () => {
    await draft.flush();
    const w = window.open("about:blank", "_blank");
    try { const r = await webApi.preview(); if (w) w.location.href = r.url; } catch (e) { w?.close(); toast({ variant: "error", title: "No preview", description: webError(e, "Try again.") }); }
  };

  if (draft.loadError) return <p className="p-6 text-sm">{webError(draft.loadError, "Couldn't open the editor.")} <button className="underline" onClick={draft.load}>Try again</button></p>;
  if (isSpecV2) {
    return (
      <div className="mx-auto grid max-w-[640px] gap-3 p-6 text-sm">
        <p className="font-semibold">This draft uses the new website builder.</p>
        <p className="text-[var(--haip-fg-muted)]">Change its pages, text or look with the art director, or open the preview to see it as guests will.
          To go back to the classic editor, restore an older version from the Versions list on the Website page.</p>
        <div className="flex flex-wrap gap-2">
          <Link href="/dashboard/marketing/website/builder" className={btnPrimary}>Open the art director</Link>
          <button type="button" className={btn} onClick={preview}>Open preview</button>
          <Link href="/dashboard/marketing/website" className={btn}>Back to Website</Link>
        </div>
      </div>
    );
  }
  if (!doc || !page || !liveData) return <div className="p-6 text-sm text-[var(--haip-fg-muted)]">Opening the editor…</div>;

  const shared = { draft, page, live: liveData, env, media: mediaList, pickPhoto, setPageId, selected, setSelected: select, touched };
  const status = draft.version?.status;
  const topBar = (
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2">
      <Link href="/dashboard/marketing/website" className={btn} aria-label="Back to Website"><ArrowLeft className="h-4 w-4" aria-hidden="true" /></Link>
      <select className="min-h-9 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-2 text-sm font-semibold" value={page.id}
        onChange={e => { setPageId(e.target.value); setSelected(null); }} aria-label="Page">
        {doc.pages.map(p => <option key={p.id} value={p.id}>{p.title}{p.key === "stay" ? " (template)" : SPEC.system_pages[p.key]?.system ? " (HAIP)" : ""}</option>)}
      </select>
      {!phone && <div className="flex rounded-full bg-[var(--haip-surface)] p-0.5" role="group" aria-label="Editor view">
        {(["ai", "builder"] as const).map(m => <button key={m} type="button" aria-pressed={mode === m} onClick={() => setMode(m)}
          className={`min-h-8 rounded-full px-3 text-[13px] font-semibold ${mode === m ? "bg-[var(--haip-card)] shadow-sm" : "text-[var(--haip-fg-muted)]"}`}>{m === "ai" ? "AI developer" : "Builder"}</button>)}
      </div>}
      {!phone && mode === "ai" && <div className="flex rounded-full bg-[var(--haip-surface)] p-0.5" role="group" aria-label="Device">
        {(["desktop", "tablet", "phone"] as const).map(d => <button key={d} type="button" aria-pressed={device === d} onClick={() => setDevice(d)}
          className={`min-h-8 rounded-full px-3 text-[13px] font-semibold capitalize ${device === d ? "bg-[var(--haip-card)] shadow-sm" : "text-[var(--haip-fg-muted)]"}`}>{d}</button>)}
      </div>}
      <span className="flex-1" />
      <button type="button" className={btn} onClick={draft.undo} disabled={!draft.canUndo} aria-label="Undo"><Undo2 className="h-4 w-4" aria-hidden="true" /></button>
      <button type="button" className={btn} onClick={draft.redo} disabled={!draft.canRedo} aria-label="Redo"><Redo2 className="h-4 w-4" aria-hidden="true" /></button>
      <span className={`text-xs ${draft.state === "error" || draft.state === "conflict" ? "font-semibold text-[var(--haip-status-warning-fg)]" : "text-[var(--haip-fg-subtle)]"}`} role="status">
        {SAVE_LABEL[draft.state]}{draft.state === "conflict" && <> · <button className="underline" onClick={draft.load}>Reload</button></>}
      </span>
      {status && <StatusPill tone={status === "draft" ? "warning" : status === "in_review" ? "info" : "success"}>v{draft.version?.number} {status.replace("_", " ")}</StatusPill>}
      <button type="button" className={btn} onClick={preview}><Eye className="mr-1 h-4 w-4" aria-hidden="true" />Preview</button>
      <button type="button" className={btnPrimary} disabled={submit.isPending || (status !== "draft" && !(canPublish && status === "in_review"))} onClick={() => submit.mutate()}>
        {submit.isPending ? "…" : canPublish ? "Publish" : status === "in_review" ? "Waiting for approval" : "Send for approval"}
      </button>
    </div>
  );

  return (
    <div className="flex h-[calc(100dvh-64px)] min-h-[560px] flex-col max-md:h-auto">
      {topBar}
      {draft.problems.length > 0 && <div className="bg-[var(--haip-status-warning-bg)] px-3 py-1.5 text-[13px] text-[var(--haip-status-warning-fg)]">{draft.problems.join(" · ")}</div>}
      {phone ? <PhoneEditor {...shared} /> : mode === "builder" ? (
        <PuckBuilder key={page.id + (draft.version?.number ?? "")} page={page} live={liveData} env={env} media={mediaList} pickPhoto={pickPhoto}
          onChange={content => draft.update(d => { const p = pageOf(d, page.id); if (p) p.content = content; })} />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[380px_minmax(0,1fr)]">
          <aside className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] border-r border-[var(--haip-border)] bg-[var(--haip-card)]">
            <div className="flex gap-1 border-b border-[var(--haip-border)] px-2 pt-2" role="tablist">
              {([["chat", block ? "Section" : "Ask AI"], ["add", "Add"], ["page", "Page"], ["site", "Site"]] as const).map(([k, l]) => (
                <button key={k} role="tab" aria-selected={panel === k} type="button" onClick={() => { setPanel(k); if (k !== "chat") setSelected(null); }}
                  className={`border-b-2 px-3 pb-2 pt-1 text-[13px] font-semibold ${panel === k ? "border-[var(--primary)]" : "border-transparent text-[var(--haip-fg-muted)]"}`}>{l}</button>
              ))}
            </div>
            <div className="min-h-0 overflow-y-auto">
              {panel === "chat" && block ? (
                <div className="grid gap-3 p-3">
                  <FieldPanel block={block} media={mediaList} pickPhoto={pickPhoto}
                    onChange={props => draft.update(d => setProps(d, page.id, block.props.id, props))}
                    onMove={dir => draft.update(d => moveBlock(d, page.id, block.props.id, dir))}
                    onDuplicate={() => { let id = ""; draft.update(d => { id = duplicateBlock(d, page.id, block.props.id); }); if (id) setSelected(id); }}
                    onDelete={() => { draft.update(d => removeBlock(d, page.id, block.props.id)); setSelected(null); }} />
                  <button type="button" className={btn} onClick={() => setSelected(null)}>Back to the AI developer</button>
                </div>
              ) : panel === "chat" ? <AiChat draft={draft} onTouched={ids => setTouched(new Set(ids))} />
                : panel === "add" ? (
                <div className="grid gap-2 p-3">
                  <p className="text-[13px] text-[var(--haip-fg-subtle)]">Adds below the selected section, or at the end of the page.</p>
                  <div className="grid grid-cols-2 gap-2">
                    {ADDABLE.map(a => <button key={a.type} type="button" className="grid gap-0.5 rounded-xl border border-[var(--haip-border)] p-2.5 text-left hover:border-[var(--primary)]"
                      onClick={() => { let id = ""; draft.update(d => { id = addBlock(d, page.id, a.type, selected); }); setSelected(id); setPanel("chat"); }}>
                      <b className="text-[13px]">{a.label}</b><span className="text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]">{a.desc}</span></button>)}
                  </div>
                  <button type="button" className={btn} onClick={() => { const t = window.prompt("Name of the new page"); if (t) { let id = ""; draft.update(d => { id = addPage(d, t); }); setPageId(id); } }}>
                    <Plus className="mr-1 h-4 w-4" aria-hidden="true" />New page</button>
                </div>
              ) : panel === "page" ? <div className="p-3"><PagePanel doc={doc} page={page} host={site.url.replace(/^https?:\/\//, "")} update={draft.update} /></div>
                : <div className="p-3"><SitePanel doc={doc} update={draft.update} /></div>}
            </div>
          </aside>
          <Canvas live={liveData} page={page} env={env} device={device} selectedId={selected} flash={touched} onSelect={select} />
        </div>
      )}
      <PhotoPicker open={!!picker} onClose={() => setPicker(null)} media={mediaList} loading={media.isLoading} onPick={ref => picker?.(ref)} />
    </div>
  );
}
