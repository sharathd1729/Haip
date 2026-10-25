"use client";
// "Change something": the owner types what they want in their own words; HAIP's AI makes the change on the draft and says
// what it did, with Undo. Nothing goes live until Publish.
import { useEffect, useRef, useState } from "react";
import { Drawer } from "@/components/ui/kit";
import { btn, btnPrimary } from "@/components/marketing/studio/types";
import { webError } from "@/lib/website";
import { builderApi, type ChangeArtifact, type Job } from "@/lib/websiteBuilder";

const IDEAS = ["Use a night photo at the top", "Change my WhatsApp number to …", "Add our guest reviews", "Make the colours calmer",
  "Show the caravans first", "Remove the questions section"];

interface Done { id: string; text: string; reply: string; canUndo: boolean; failed?: boolean }

export function ChangeSheet({ open, onClose, onChanged }: { open: boolean; onClose: () => void; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<Done[]>([]);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  async function waitFor(id: string): Promise<Job> {
    for (let i = 0; i < 60 && alive.current; i++) {
      const job = await builderApi.job(id);
      if (job.status === "ready" || job.status === "failed") return job;
      await new Promise(r => setTimeout(r, 2000));
    }
    throw new Error("This is taking longer than usual. Check again in a minute.");
  }

  async function send() {
    const ask = text.trim();
    if (ask.length < 3 || busy) return;
    setBusy(true);
    try {
      const job = await waitFor((await builderApi.change(ask)).id);
      const art = (job.artifact || {}) as Partial<ChangeArtifact>;
      setHistory(h => [{ id: job.id, text: ask, reply: job.status === "failed" ? (job.error || "That didn't work. Try saying it another way.") : art.reply || "Done.",
        canUndo: !!art.can_undo, failed: job.status === "failed" }, ...h]);
      if (job.status === "ready" && art.edits) onChanged();
      setText("");
    } catch (e) {
      setHistory(h => [{ id: `err-${Date.now()}`, text: ask, reply: webError(e, "That didn't work. Try again."), canUndo: false, failed: true }, ...h]);
    } finally { setBusy(false); }
  }

  async function undo(d: Done) {
    try {
      await builderApi.undo(d.id);
      setHistory(h => h.map(x => (x.id === d.id ? { ...x, canUndo: false, reply: x.reply + " (undone)" } : x)));
      onChanged();
    } catch (e) {
      setHistory(h => h.map(x => (x.id === d.id ? { ...x, canUndo: false, reply: webError(e, "Couldn't undo that.") } : x)));
    }
  }

  return (
    <Drawer open={open} onOpenChange={o => !o && onClose()} title="Change something" description="Say what you want, the way you'd tell a friend."
      footer={<button className={btn} onClick={onClose}>Done</button>}>
      <div className="grid gap-4">
        <label className="grid gap-2">
          <span className="sr-only">What would you like to change?</span>
          <textarea className="min-h-[110px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-3 text-base"
            placeholder="e.g. Put the caravan night photo at the top" value={text} maxLength={500} disabled={busy}
            onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        </label>
        <button className={btnPrimary} disabled={busy || text.trim().length < 3} onClick={send}>{busy ? "Changing your website…" : "Change it"}</button>
        {!history.length && (
          <div className="flex flex-wrap gap-2">
            {IDEAS.map(i => <button key={i} type="button" className="min-h-11 rounded-full border border-dashed border-[var(--haip-border)] px-3 text-sm text-[var(--haip-fg-muted)]"
              onClick={() => setText(i.replace(" …", " "))}>{i}</button>)}
          </div>
        )}
        <ul className="grid gap-3" aria-live="polite">
          {history.map(d => (
            <li key={d.id} className={`grid gap-1.5 rounded-xl border p-3 ${d.failed ? "border-[var(--haip-status-warning-fg)]" : "border-[var(--haip-border)]"}`}>
              <span className="text-sm text-[var(--haip-fg-muted)]">You: {d.text}</span>
              <span className="text-[15px]">{d.reply}</span>
              {d.canUndo && <button className="justify-self-start text-sm font-semibold underline underline-offset-4" onClick={() => undo(d)}>Undo</button>}
            </li>
          ))}
        </ul>
      </div>
    </Drawer>
  );
}
