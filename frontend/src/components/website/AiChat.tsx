"use client";
// "Ask the AI developer": the owner writes what to change; HAIP queues a job (Celery), the AI returns operations that
// the server validates and saves as the draft. Each answer is a change card with Undo (restores the document as it was
// before the request) and the changed sections are marked on the page.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Sparkles } from "lucide-react";
import { btnPrimary, inputCls } from "@/components/marketing/studio/types";
import { webApi, webError, type AiJob } from "@/lib/website";
import type { SiteDoc } from "@/site-blocks/types";
import type { Draft } from "./useDraft";

interface Msg { id: string; me?: boolean; text: string; job?: AiJob; before?: SiteDoc; undone?: boolean }

const SUGGESTIONS = [
  "Write the whole site from my business details",
  "Make the home page headline warmer and more specific",
  "Add a monsoon offer banner above the stays",
  "Add an FAQ page for long stays",
  "Write the missing search descriptions",
];

export function AiChat({ draft, onTouched }: { draft: Draft; onTouched: (ids: string[]) => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([{ id: "hello", text: "Hi, I'm your website developer. Tell me what to change and I'll make it in the draft, which you can undo. I don't touch prices, availability or policies: those come from Bookings and Settings." }]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs]);

  const poll = async (job: AiJob, before: SiteDoc | undefined, msgId: string) => {
    for (let i = 0; i < 90; i++) {
      await new Promise(r => setTimeout(r, i < 5 ? 1500 : 3000));
      const j = await webApi.aiJob(job.id).catch(() => null);
      if (!j || j.status === "pending" || j.status === "running") continue;
      if (j.status === "ready") await draft.load();
      setMsgs(m => m.map(x => (x.id === msgId ? { ...x, job: j, before, text: j.status === "ready" ? j.result?.reply || "Done." : j.error || "That didn't work. Try again." } : x)));
      if (j.result?.touched?.length) onTouched(j.result.touched);
      return;
    }
    setMsgs(m => m.map(x => (x.id === msgId ? { ...x, text: "This is taking longer than usual. Check back in a minute." } : x)));
  };

  const send = async (message: string) => {
    const q = message.trim();
    if (!q || busy) return;
    setBusy(true);
    setText("");
    await draft.flush();
    const before = draft.doc ? structuredClone(draft.doc) : undefined;
    const meId = `m${Date.now()}`, aiId = `a${Date.now()}`;
    setMsgs(m => [...m, { id: meId, me: true, text: q }, { id: aiId, text: "" }]);
    try {
      const generate = /write the whole site|write my site|build my site/i.test(q);
      const job = generate ? await webApi.aiGenerate() : await webApi.aiEdit(q);
      await poll(job, before, aiId);
    } catch (e) {
      setMsgs(m => m.map(x => (x.id === aiId ? { ...x, text: webError(e, "The AI developer couldn't start. Try again.") } : x)));
    } finally { setBusy(false); }
  };

  const undo = (msg: Msg) => {
    if (!msg.before) return;
    draft.replace(msg.before);
    setMsgs(m => m.map(x => (x.id === msg.id ? { ...x, undone: true } : x)));
    onTouched([]);
  };

  const submit = (e: FormEvent) => { e.preventDefault(); send(text); };
  return (
    <div className="grid h-full min-h-0 grid-rows-[minmax(0,1fr)_auto]">
      <div className="grid content-start gap-3 overflow-y-auto p-3" aria-live="polite">
        {msgs.map(m => m.me ? (
          <div key={m.id} className="max-w-[90%] justify-self-end rounded-2xl rounded-tr-md bg-primary px-3 py-2 text-sm text-primary-foreground">{m.text}</div>
        ) : (
          <div key={m.id} className="max-w-[94%] rounded-2xl rounded-tl-md bg-[var(--haip-surface)] px-3 py-2 text-sm leading-relaxed">
            {m.text || <span className="inline-flex gap-1" aria-label="Working"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--haip-fg-subtle)]" /><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--haip-fg-subtle)] [animation-delay:150ms]" /><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--haip-fg-subtle)] [animation-delay:300ms]" /></span>}
            {m.job?.result && (m.job.result.changes.length > 0 || m.job.result.refused.length > 0) && (
              <div className="mt-2 grid gap-1.5 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-2.5">
                {m.job.result.changes.length > 0 && <><b className="text-[13px]">{m.job.result.changes.length} change{m.job.result.changes.length > 1 ? "s" : ""} in the draft</b>
                  <ul className="list-disc pl-4 text-[13px]">{m.job.result.changes.slice(0, 12).map((c, i) => <li key={i}>{c}</li>)}</ul></>}
                {m.job.result.refused.length > 0 && <ul className="list-disc pl-4 text-[13px] text-[var(--haip-status-warning-fg)]">{m.job.result.refused.map((c, i) => <li key={i}>{c}</li>)}</ul>}
                {m.job.result.changes.length > 0 && (m.undone ? <span className="text-xs text-[var(--haip-fg-subtle)]">Undone</span> :
                  <div className="flex gap-1.5"><button type="button" className="min-h-9 rounded-lg border border-[var(--haip-border)] px-3 text-[13px] font-semibold" onClick={() => undo(m)}>Undo</button>
                    <button type="button" className="min-h-9 rounded-lg border border-[var(--haip-border)] px-3 text-[13px] font-semibold" onClick={() => onTouched([])}>Keep</button></div>)}
              </div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <div className="border-t border-[var(--haip-border)] p-3">
        <div className="mb-2 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map(s => <button key={s} type="button" disabled={busy} onClick={() => send(s)}
            className="rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-1.5 text-left text-[12.5px] hover:border-[var(--primary)] disabled:opacity-50">{s}</button>)}
        </div>
        <form className="flex gap-2" onSubmit={submit}>
          <textarea className={`${inputCls} min-h-11 resize-none`} rows={1} value={text} placeholder="Tell the AI what to change" aria-label="Message the AI developer"
            onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }} />
          <button type="submit" className={btnPrimary} disabled={busy || !text.trim()}><Sparkles className="mr-1 h-4 w-4" aria-hidden="true" />Send</button>
        </form>
      </div>
    </div>
  );
}
