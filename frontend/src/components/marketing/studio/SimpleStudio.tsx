"use client";
// Marketing Studio home: the existing studio laid out as one path, in the order an owner works (owner, Oct 2026: "where is
// the library, where are the insights, where is the plan, where do I publish"). Every button opens an existing screen;
// nothing is new except "Make a post", which creates a post, lets the AI write it and opens the usual review panel.
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, Drawer } from "@/components/ui/kit";
import { ContentDrawer } from "./ContentDrawer";
import { STUDIO, btn, btnPrimary, studioError, type ContentItem } from "./types";

type Item = { label: string; tab?: string; href?: string; primary?: boolean; onClick?: () => void };
interface Step { n: number; title: string; text: string; items: Item[]; note?: string }

export function SimpleStudio({ go, onMore }: { go: (leaf: string) => void; onMore: () => void }) {
  const [making, setMaking] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const waiting = useQuery<ContentItem[]>({ queryKey: ["studio-content", "in_review"],
    queryFn: () => api.get(`${STUDIO}/content`, { params: { status: "in_review" } }).then(r => r.data) });
  const n = waiting.data?.length ?? 0;

  const steps: Step[] = [
    { n: 1, title: "Set up", text: "Your brand voice, logo and colours, and the photos and videos HAIP can use.",
      items: [{ label: "Brand voice & look", tab: "profile" }, { label: "Photos & videos (Library)", tab: "library" }] },
    { n: 2, title: "See what's working", text: "Results from Instagram, your ads and your competitors, in plain words.",
      items: [{ label: "Weekly report", tab: "report" }, { label: "Instagram insights", href: "/dashboard/instagram-insights" },
        { label: "Ads results", href: "/dashboard/marketing" }, { label: "Results by post", tab: "results" },
        { label: "Account audit", tab: "audit" }, { label: "Competitors", tab: "research" }] },
    { n: 3, title: "Plan", text: "HAIP's plan and post calendar, built from your free dates, festivals and what works.",
      items: [{ label: "Plan & calendar", tab: "plan", primary: true }, { label: "Strategy", tab: "strategy" },
        { label: "Sources HAIP reads", tab: "sources" }] },
    { n: 4, title: "Create", text: "Turn the plan into posts, reels and stories. Edit the words and photos before approving.",
      items: [{ label: "Make a post", primary: true, onClick: () => setMaking(true) }, { label: "All drafts & posts", tab: "content" },
        { label: "Videos & reels", tab: "produce" }, { label: "Creator collabs", tab: "partners" }] },
    { n: 5, title: "Approve & publish", text: "Nothing goes out until you approve it. Then it's scheduled and posted.",
      note: n > 0 ? `${n} post${n > 1 ? "s" : ""} waiting for your OK` : undefined,
      items: [{ label: n > 0 ? `Approve (${n})` : "Approvals", tab: "approvals", primary: n > 0 }, { label: "Ads", tab: "ads" },
        { label: "Google reviews", tab: "reviews" }] },
  ];

  return (
    <div className="grid gap-3">
      <p className="text-[15px] text-[var(--haip-fg-muted)]">Your marketing, step by step. Start at 1; HAIP does most of the work.</p>
      <ol className="grid gap-3">
        {steps.map(s => (
          <li key={s.n}>
            <Card><CardBody className="grid gap-3 sm:grid-cols-[auto_1fr] sm:items-start sm:gap-4">
              <span aria-hidden="true" className="grid h-10 w-10 place-items-center rounded-full bg-[var(--haip-primary-tint)] text-base font-bold text-[var(--primary)]">{s.n}</span>
              <div className="grid gap-2">
                <div>
                  <h2 className="text-lg font-semibold">{s.title}</h2>
                  <p className="text-sm text-[var(--haip-fg-muted)]">{s.text}</p>
                  {s.note && <p className="mt-1 text-sm font-semibold text-[var(--haip-status-warning-fg)]">{s.note}</p>}
                </div>
                <div className="flex flex-wrap gap-2">
                  {s.items.map(it => it.href
                    ? <Link key={it.label} href={it.href} className={btn}>{it.label}</Link>
                    : <button key={it.label} type="button" className={it.primary ? btnPrimary : btn}
                        onClick={it.onClick ?? (() => it.tab && go(it.tab))}>{it.label}</button>)}
                </div>
              </div>
            </CardBody></Card>
          </li>
        ))}
      </ol>
      <button className="min-h-11 justify-self-start text-sm text-[var(--haip-fg-muted)] underline underline-offset-4" onClick={onMore}>
        Show every section at once</button>
      <MakePost open={making} onClose={() => setMaking(false)} onReady={id => { setMaking(false); setOpen(id); }} />
      <ContentDrawer id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

const IDEAS = ["A weekend trip for couples", "Monsoon offer", "What guests loved last month", "Our caravan at night"];

/** "Make a post": what it's about → HAIP creates the post, writes it and picks photos → the usual review panel opens. */
function MakePost({ open, onClose, onReady }: { open: boolean; onClose: () => void; onReady: (id: string) => void }) {
  const qc = useQueryClient();
  const [about, setAbout] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function start() {
    const title = about.trim();
    if (title.length < 3) return;
    setBusy(true); setErr("");
    try {
      const item: ContentItem = (await api.post(`${STUDIO}/content`, { kind: "post", title })).data;
      await api.post(`${STUDIO}/content/${item.id}/generate`, { brief: title });
      for (let i = 0; i < 45; i++) {                       // the AI writes in the background; about a minute at most
        const cur: ContentItem = (await api.get(`${STUDIO}/content/${item.id}`)).data;
        if (cur.generation_status === "failed") throw new Error("HAIP couldn't write this one. Try saying it another way.");
        if (cur.generation_status !== "pending") break;
        await new Promise(r => setTimeout(r, 2000));
      }
      await api.post(`${STUDIO}/content/${item.id}/pick-photos`).catch(() => null);   // the panel shows "Needs photos" if none fit
      qc.invalidateQueries({ queryKey: ["studio-content"] });
      setAbout("");
      onReady(item.id);
    } catch (e) {
      setErr(e instanceof Error && !("response" in e) ? e.message : studioError(e, "That didn't work. Try again."));
    } finally { setBusy(false); }
  }

  return (
    <Drawer open={open} onOpenChange={o => !o && !busy && onClose()} title="Make a post"
      description="What's it about? HAIP writes it and picks photos. Then you check it and approve."
      footer={<div className="flex gap-2"><button className={btn} disabled={busy} onClick={onClose}>Cancel</button>
        <button className={btnPrimary} disabled={busy || about.trim().length < 3} onClick={start}>{busy ? "Writing your post…" : "Write it for me"}</button></div>}>
      <div className="grid gap-3">
        <textarea className="min-h-[100px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-3 text-base"
          aria-label="What's the post about?" placeholder="e.g. A quiet weekend in Coorg for couples" value={about} maxLength={160}
          disabled={busy} onChange={e => setAbout(e.target.value)} />
        <div className="flex flex-wrap gap-2">{IDEAS.map(i => <button key={i} type="button" disabled={busy} onClick={() => setAbout(i)}
          className="min-h-11 rounded-full border border-dashed border-[var(--haip-border)] px-3 text-sm text-[var(--haip-fg-muted)]">{i}</button>)}</div>
        {busy && <p className="text-sm text-[var(--haip-fg-muted)]" role="status">Writing your post and choosing photos. About a minute.</p>}
        {err && <p className="text-sm font-semibold text-[var(--haip-status-danger-fg)]" role="alert">{err}</p>}
      </div>
    </Drawer>
  );
}
