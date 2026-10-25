"use client";
// The Marketing Studio home for owners who are not marketers (owner, Oct 2026: "a person with no experience can run the
// ads and the posts on their own"): four big buttons, one thing at a time. "Make a post" is guided: say what it's about,
// HAIP writes it and picks photos, then the usual review panel opens to approve and schedule. The full studio (all
// sections) stays one tap away under "More options".
import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, ImagePlus, Megaphone, PenLine } from "lucide-react";
import api from "@/lib/api";
import { Card, CardBody, Drawer } from "@/components/ui/kit";
import { ContentDrawer } from "./ContentDrawer";
import { STUDIO, btn, btnPrimary, studioError, type ContentItem } from "./types";

const IDEAS = ["A weekend trip for couples", "Monsoon offer", "What guests loved last month", "Our caravan at night",
  "A family road trip", "Behind the scenes with our host"];

export function SimpleStudio({ go, onMore }: { go: (leaf: string) => void; onMore: () => void }) {
  const [making, setMaking] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const waiting = useQuery<ContentItem[]>({ queryKey: ["studio-content", "in_review"],
    queryFn: () => api.get(`${STUDIO}/content`, { params: { status: "in_review" } }).then(r => r.data) });
  const n = waiting.data?.length ?? 0;
  return (
    <div className="grid gap-4">
      <p className="text-[15px] text-[var(--haip-fg-muted)]">What would you like to do?</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Big icon={<PenLine size={24} />} title="Make a post" text="Tell HAIP what it's about. It writes it and picks the photos." onClick={() => setMaking(true)} primary />
        <Big icon={<Megaphone size={24} />} title="Run an ad" text="Boost a post or start an ad that brings WhatsApp enquiries." onClick={() => go("ads")} />
        <Big icon={<BarChart3 size={24} />} title="What's working" text="This week's results in plain words, and what to do next." onClick={() => go("report")} />
        <Big icon={<ImagePlus size={24} />} title="My photos" text="Add photos and videos HAIP can use in posts and on your website." onClick={() => go("library")} />
      </div>
      {n > 0 && (
        <Card><CardBody className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[15px]"><b className="font-semibold">{n} post{n > 1 ? "s" : ""} waiting for your OK.</b>
            <span className="block text-sm text-[var(--haip-fg-muted)]">Nothing is posted until you approve it.</span></p>
          <button className={btnPrimary} onClick={() => go("approvals")}>Review now</button>
        </CardBody></Card>
      )}
      <button className="justify-self-start min-h-11 text-sm text-[var(--haip-fg-muted)] underline underline-offset-4" onClick={onMore}>More options</button>
      <MakePost open={making} onClose={() => setMaking(false)} onReady={id => { setMaking(false); setOpen(id); }} />
      <ContentDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function Big({ icon, title, text, onClick, primary }: { icon: ReactNode; title: string; text: string; onClick: () => void; primary?: boolean }) {
  return (
    <button type="button" onClick={onClick}
      className={`grid min-h-[96px] grid-cols-[auto_1fr] items-center gap-4 rounded-2xl border p-5 text-left transition-transform active:scale-[0.98] ${primary ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)] bg-[var(--haip-card)]"}`}>
      <span aria-hidden="true">{icon}</span>
      <span><b className="block text-lg font-semibold">{title}</b><span className={`block text-sm ${primary ? "opacity-90" : "text-[var(--haip-fg-muted)]"}`}>{text}</span></span>
    </button>
  );
}

/** Step 1 of "Make a post": what it's about. Then HAIP creates the post, writes it and picks photos, and hands over to the
 *  review panel (step 2: look and approve; step 3: schedule). */
function MakePost({ open, onClose, onReady }: { open: boolean; onClose: () => void; onReady: (id: string) => void }) {
  const qc = useQueryClient();
  const [about, setAbout] = useState("");
  const [state, setState] = useState<"idle" | "writing" | "error">("idle");
  const [err, setErr] = useState("");

  async function start() {
    const title = about.trim();
    if (title.length < 3) return;
    setState("writing"); setErr("");
    try {
      const item: ContentItem = (await api.post(`${STUDIO}/content`, { kind: "post", title })).data;
      await api.post(`${STUDIO}/content/${item.id}/generate`, { brief: title });
      for (let i = 0; i < 45; i++) {                       // the AI writes in the background; about a minute at most
        const cur: ContentItem = (await api.get(`${STUDIO}/content/${item.id}`)).data;
        if (cur.generation_status === "failed") throw new Error("HAIP couldn't write this one. Try saying it another way.");
        if (cur.generation_status !== "pending") break;
        await new Promise(r => setTimeout(r, 2000));
      }
      await api.post(`${STUDIO}/content/${item.id}/pick-photos`).catch(() => null);   // best effort: the panel shows "Needs photos"
      qc.invalidateQueries({ queryKey: ["studio-content"] });
      setAbout(""); setState("idle");
      onReady(item.id);
    } catch (e) {
      setState("error"); setErr(e instanceof Error && !("response" in e) ? e.message : studioError(e, "That didn't work. Try again."));
    }
  }

  return (
    <Drawer open={open} onOpenChange={o => !o && state !== "writing" && onClose()} title="Make a post"
      description="Step 1 of 3: what's it about? Next you look at it, then you choose when it goes out."
      footer={<div className="flex gap-2"><button className={btn} disabled={state === "writing"} onClick={onClose}>Cancel</button>
        <button className={btnPrimary} disabled={state === "writing" || about.trim().length < 3} onClick={start}>
          {state === "writing" ? "Writing your post…" : "Write it for me"}</button></div>}>
      <div className="grid gap-4">
        <textarea className="min-h-[110px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-3 text-base"
          aria-label="What's the post about?" placeholder="e.g. A quiet weekend in Coorg for couples" value={about} maxLength={160}
          disabled={state === "writing"} onChange={e => setAbout(e.target.value)} />
        <div className="flex flex-wrap gap-2">
          {IDEAS.map(i => <button key={i} type="button" disabled={state === "writing"} onClick={() => setAbout(i)}
            className="min-h-11 rounded-full border border-dashed border-[var(--haip-border)] px-3 text-sm text-[var(--haip-fg-muted)]">{i}</button>)}
        </div>
        {state === "writing" && <p className="text-sm text-[var(--haip-fg-muted)]" role="status">HAIP is writing your post and choosing photos. This takes about a minute.</p>}
        {state === "error" && <p className="text-sm font-semibold text-[var(--haip-status-danger-fg)]" role="alert">{err}</p>}
      </div>
    </Drawer>
  );
}
