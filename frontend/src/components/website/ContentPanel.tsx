"use client";
// Website page: content tools (website phase 5). Guides (written by HAIP's AI or by hand, shown on the site only once
// approved), Google reviews (shown only after you record that the guest agreed), and importing a photo or an MP4 (from
// your phone or exported from Canva) into the library; an MP4 can become the moving top of the home page.
// Backend: endpoints/website_growth.py (website_blog, website_reviews, /media/import).
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Film, Star } from "lucide-react";
import { Card, CardBody, Drawer, StatusPill } from "@/components/ui/kit";
import { btn, btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { useToast } from "@/components/ui/toast";
import { webError } from "@/lib/website";
import { growthApi, type Guide, type LibraryItem } from "@/lib/websiteGrowth";
import type { useDraft } from "./useDraft";

type Draft = ReturnType<typeof useDraft>;
type Sheet = null | "guides" | "reviews" | "media";

export function ContentPanel({ canApprove, draft }: { canApprove: boolean; draft: Draft }) {
  const [sheet, setSheet] = useState<Sheet>(null);
  const close = () => setSheet(null);
  const tile = (k: Sheet, icon: ReactNode, title: string, text: string) => (
    <button type="button" onClick={() => setSheet(k)} className="grid min-h-[76px] grid-cols-[auto_1fr] items-center gap-3 rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-4 text-left">
      <span aria-hidden="true" className="text-[var(--primary)]">{icon}</span>
      <span><b className="block font-semibold">{title}</b><span className="block text-sm text-[var(--haip-fg-muted)]">{text}</span></span>
    </button>
  );
  return (
    <Card><CardBody className="grid gap-3">
      <p className="font-semibold">More for your website</p>
      <div className="grid gap-3 sm:grid-cols-3">
        {tile("guides", <BookOpen size={22} />, "Guides", "Helpful articles that bring guests from Google.")}
        {tile("reviews", <Star size={22} />, "Google reviews", "Choose which reviews show on your site.")}
        {tile("media", <Film size={22} />, "Video or Canva design", "Add an MP4 or a design you exported.")}
      </div>
      <GuidesSheet open={sheet === "guides"} onClose={close} canApprove={canApprove} />
      <ReviewsSheet open={sheet === "reviews"} onClose={close} canApprove={canApprove} />
      <MediaSheet open={sheet === "media"} onClose={close} draft={draft} canApprove={canApprove} />
    </CardBody></Card>
  );
}

function GuidesSheet({ open, onClose, canApprove }: { open: boolean; onClose: () => void; canApprove: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const list = useQuery({ queryKey: ["web-guides"], queryFn: growthApi.guides, enabled: open,
    refetchInterval: q => ((q.state.data || []).some(g => g.generation_status === "pending") ? 4000 : false) });
  const [topic, setTopic] = useState("");
  const [edit, setEdit] = useState<Guide | null>(null);
  const done = () => qc.invalidateQueries({ queryKey: ["web-guides"] });
  const fail = (title: string) => (e: unknown) => toast({ variant: "error", title, description: webError(e, "Try again.") });
  const write = useMutation({ mutationFn: () => growthApi.writeGuide(topic.trim()), onSuccess: () => { setTopic(""); done(); }, onError: fail("Couldn't start") });
  const act = useMutation({ mutationFn: (a: { g: Guide; action: "submit" | "approve" | "archive" }) => growthApi.guideAction(a.g.id, a.action, a.g.version_id || ""),
    onSuccess: (_d, a) => { done(); toast({ variant: "success", title: a.action === "approve" ? "It's on your website" : a.action === "archive" ? "Taken down" : "Sent for approval" }); },
    onError: fail("Not done") });
  const save = useMutation({ mutationFn: (g: Guide) => growthApi.editGuide(g.id, g.payload!), onSuccess: () => { setEdit(null); done(); }, onError: fail("Not saved") });
  const setP = (k: keyof NonNullable<Guide["payload"]>, v: string) => edit?.payload && setEdit({ ...edit, payload: { ...edit.payload, [k]: v } });
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) { setEdit(null); onClose(); } }} title={edit ? "Edit guide" : "Guides"}
      footer={edit ? <div className="flex gap-2"><button className={btn} onClick={() => setEdit(null)}>Back</button>
        <button className={btnPrimary} disabled={save.isPending} onClick={() => save.mutate(edit)}>{save.isPending ? "Saving…" : "Save"}</button></div> : undefined}>
      {edit?.payload ? (
        <div className="grid gap-3">
          <label className="grid gap-1"><span className="text-sm font-semibold">Title</span><input className={inputCls} value={edit.payload.title} maxLength={110} onChange={e => setP("title", e.target.value)} /></label>
          <label className="grid gap-1"><span className="text-sm font-semibold">Short summary</span><textarea className={inputCls} rows={2} maxLength={240} value={edit.payload.excerpt} onChange={e => setP("excerpt", e.target.value)} /></label>
          <label className="grid gap-1"><span className="text-sm font-semibold">Text</span><textarea className={inputCls} rows={14} maxLength={9000} value={edit.payload.body} onChange={e => setP("body", e.target.value)} />
            <span className="text-xs text-[var(--haip-fg-muted)]">Empty line = new paragraph. Start a line with ## for a sub-heading. No prices.</span></label>
        </div>
      ) : (
        <div className="grid gap-4">
          <div className="grid gap-2"><span className="text-sm font-semibold">What should the guide be about?</span>
            <input className={inputCls} value={topic} maxLength={160} onChange={e => setTopic(e.target.value)} placeholder="A weekend in Coorg with kids" />
            <button className={btnPrimary} disabled={topic.trim().length < 4 || write.isPending} onClick={() => write.mutate()}>{write.isPending ? "Starting…" : "Write it for me"}</button>
            <span className="text-xs text-[var(--haip-fg-muted)]">HAIP writes from your own details. You read it, change anything, then approve it. Nothing goes on your website before that.</span></div>
          {list.isLoading ? <div className="h-24 animate-pulse rounded-xl bg-[var(--haip-border)]" />
            : list.isError ? <p className="text-sm">Couldn&apos;t load guides. <button className="underline" onClick={() => list.refetch()}>Try again</button></p>
            : !list.data?.length ? <p className="text-sm text-[var(--haip-fg-muted)]">No guides yet.</p>
            : <ul className="grid gap-2">{list.data.map(g => (
              <li key={g.id} className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3">
                <span className="flex flex-wrap items-center gap-2"><b className="font-semibold">{g.payload?.title || g.title}</b>
                  <StatusPill tone={g.live ? "success" : g.generation_status === "failed" ? "danger" : "neutral"}>
                    {g.generation_status === "pending" ? "Writing…" : g.generation_status === "failed" ? "Failed" : g.live ? "On your website" : g.status === "in_review" ? "Waiting for approval" : "Draft"}</StatusPill></span>
                {g.generation_error && <span className="text-sm text-[var(--haip-fg-muted)]">{g.generation_error}</span>}
                {g.payload && <span className="flex flex-wrap gap-2">
                  <button className={btn} onClick={() => setEdit(g)}>Read and edit</button>
                  {(g.status === "draft" || g.status === "rejected") && <button className={btn} disabled={act.isPending} onClick={() => act.mutate({ g, action: "submit" })}>Send for approval</button>}
                  {canApprove && g.status === "in_review" && <button className={btnPrimary} disabled={act.isPending} onClick={() => act.mutate({ g, action: "approve" })}>Approve and show</button>}
                  {canApprove && <button className={btn} disabled={act.isPending} onClick={() => act.mutate({ g, action: "archive" })}>Take down</button>}
                </span>}
              </li>))}</ul>}
        </div>
      )}
    </Drawer>
  );
}

function ReviewsSheet({ open, onClose, canApprove }: { open: boolean; onClose: () => void; canApprove: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const list = useQuery({ queryKey: ["web-reviews"], queryFn: growthApi.reviews, enabled: open });
  const [noteFor, setNoteFor] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const consent = useMutation({ mutationFn: (a: { id: string; note: string | null }) => growthApi.reviewConsent(a.id, a.note),
    onSuccess: d => { qc.setQueryData(["web-reviews"], d); setNoteFor(null); setNote(""); },
    onError: e => toast({ variant: "error", title: "Not saved", description: webError(e, "Try again.") }) });
  const sync = useMutation({ mutationFn: growthApi.importReviews, onSuccess: () => toast({ variant: "success", title: "Importing your Google reviews. Check back in a minute." }),
    onError: e => toast({ variant: "error", title: "Couldn't import", description: webError(e, "Try again.") }) });
  return (
    <Drawer open={open} onOpenChange={o => !o && onClose()} title="Google reviews">
      <div className="grid gap-3 text-[15px]">
        <p className="text-sm text-[var(--haip-fg-muted)]">A review shows on your website only after you note how the guest agreed (for example &ldquo;asked on WhatsApp, said yes&rdquo;). First names only. Your star average counts every review.</p>
        {canApprove && <button className={btn} disabled={sync.isPending} onClick={() => sync.mutate()}>Import from Google now</button>}
        {list.isLoading ? <div className="h-24 animate-pulse rounded-xl bg-[var(--haip-border)]" />
          : list.isError ? <p className="text-sm">Couldn&apos;t load reviews. <button className="underline" onClick={() => list.refetch()}>Try again</button></p>
          : !list.data?.length ? <p className="text-sm">No reviews yet. Connect Google Business Profile in Marketing › Studio, then import.</p>
          : <ul className="grid gap-2">{list.data.map(r => (
            <li key={r.id} className="grid gap-2 rounded-xl border border-[var(--haip-border)] p-3">
              <span className="flex flex-wrap items-center gap-2"><b className="font-semibold">{(r.reviewer || "Guest").split(" ")[0]}</b>
                <span aria-label={`${r.rating || 0} stars`}>{"★".repeat(r.rating || 0)}</span>
                {r.shown && <StatusPill tone="success">On your website</StatusPill>}</span>
              {r.comment && <span className="text-sm">{r.comment.slice(0, 280)}</span>}
              {canApprove && (noteFor === r.id ? (
                <span className="grid gap-2"><input className={inputCls} value={note} maxLength={300} onChange={e => setNote(e.target.value)} placeholder="How did the guest agree?" />
                  <button className={btnPrimary} disabled={note.trim().length < 3 || consent.isPending} onClick={() => consent.mutate({ id: r.id, note: note.trim() })}>Show on website</button></span>
              ) : r.shown ? <button className={btn} disabled={consent.isPending} onClick={() => consent.mutate({ id: r.id, note: null })}>Hide from website</button>
                : (r.rating || 0) >= 4 && r.comment ? <button className={btn} onClick={() => { setNoteFor(r.id); setNote(""); }}>Guest agreed to share</button> : null)}
            </li>))}</ul>}
      </div>
    </Drawer>
  );
}

function MediaSheet({ open, onClose, draft, canApprove }: { open: boolean; onClose: () => void; draft: Draft; canApprove: boolean }) {
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [canva, setCanva] = useState(false);
  const [alt, setAlt] = useState("");
  const [added, setAdded] = useState<LibraryItem | null>(null);
  const up = useMutation({ mutationFn: () => growthApi.importMedia(file!, canva ? "canva" : "upload", alt.trim() || undefined),
    onSuccess: a => { setAdded(a); setFile(null); toast({ variant: "success", title: "Added to your library" }); },
    onError: e => toast({ variant: "error", title: "Not added", description: webError(e, "Use a JPG, PNG or MP4 (up to 90 seconds).") }) });
  const useAsHero = async () => {
    if (!added) return;
    draft.update(d => {
      const hero = (d as unknown as { pages: { sections: { type: string; variant: string; slots: Record<string, unknown> }[] }[] }).pages[0]?.sections.find(s => s.type === "hero");
      if (hero) { hero.variant = "video"; hero.slots.video = added.ref; }
    });
    const err = await draft.flush();
    if (err) { toast({ variant: "error", title: "Not changed", description: webError(err, "Try again.") }); draft.load(); return; }
    toast({ variant: "success", title: "Your home page starts with the video. Publish to show it." });
    onClose();
  };
  return (
    <Drawer open={open} onOpenChange={o => { if (!o) { setAdded(null); onClose(); } }} title="Video or Canva design">
      <div className="grid gap-4 text-[15px]">
        <p className="text-sm text-[var(--haip-fg-muted)]">Made something in Canva? Download it as PNG, JPG or MP4 and add it here. HAIP removes sound from videos; they play muted on loop, and visitors who prefer less motion see the photo instead.</p>
        <input type="file" accept="image/jpeg,image/png,video/mp4" className="min-h-11" onChange={e => setFile(e.target.files?.[0] || null)} />
        <label className="grid gap-1"><span className="text-sm font-semibold">Describe it (for screen readers)</span>
          <input className={inputCls} value={alt} maxLength={300} onChange={e => setAlt(e.target.value)} placeholder="Our pool at sunset" /></label>
        <label className="flex min-h-11 items-center gap-3"><input type="checkbox" className="h-5 w-5 accent-[var(--primary)]" checked={canva} onChange={e => setCanva(e.target.checked)} />
          <span>This is a Canva design</span></label>
        <button className={btnPrimary} disabled={!file || up.isPending} onClick={() => up.mutate()}>{up.isPending ? "Adding…" : "Add to my library"}</button>
        {added?.mime_type === "video/mp4" && canApprove && (draft.doc as { spec_version?: number } | null)?.spec_version === 2 && (
          <button className={btn} onClick={useAsHero}>Use it at the top of my home page</button>)}
      </div>
    </Drawer>
  );
}
