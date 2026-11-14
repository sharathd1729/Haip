"use client";
// Ask Yaad: questions answered from your own calls (POST /me/ask, then poll GET /me/ask/{id}; the answer is written in
// the background). Quick prompts for the common asks, answers formatted the way they would read on WhatsApp, the calls
// each answer came from, and Share / Copy. The conversation stays on this device only (a convenience, not a record).
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import api from "@/lib/api";
import { ArrowRight, Copy, Loader2, Send, AskBubble } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { dayLabel, istDay } from "@/lib/personal";

interface Source { call_id: string; title: string | null; contact: string; at: string }
interface Turn { id: string; question: string; status: "pending" | "done" | "failed"; answer?: string; error?: string; sources?: Source[] }

const PROMPTS = ["Summarise today", "My action items", "What did I promise people?", "What's coming up this week?"];
const STORE = "yaad.ask.v1";
const POLL_MS = 1500;
const GIVE_UP_MS = 90_000;

function load(): Turn[] {
  try { return JSON.parse(localStorage.getItem(STORE) ?? "[]").filter((t: Turn) => t.status !== "pending"); } catch { return []; }
}
function save(turns: Turn[]) {
  try { localStorage.setItem(STORE, JSON.stringify(turns.slice(-20))); } catch { /* private mode: keep it in memory */ }
}

/** *bold* and "* " list lines, the WhatsApp format the answers come in. Text only: nothing is rendered as HTML. */
function Formatted({ text }: { text: string }) {
  const bold = (line: string) => line.split(/(\*[^*\n]+\*)/g).map((part, i) =>
    /^\*[^*\n]+\*$/.test(part) ? <strong key={i} className="font-semibold">{part.slice(1, -1)}</strong> : <span key={i}>{part}</span>);
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) blocks.push(<ul key={`l${blocks.length}`} className="grid list-disc gap-1 pl-5 marker:text-[var(--y-ink-3)]">{list.map((l, i) => <li key={i}>{bold(l)}</li>)}</ul>);
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const item = line.match(/^\s*[*•-]\s+(.*)$/);
    if (item) { list.push(item[1]); continue; }
    flush();
    if (line.trim()) blocks.push(<p key={`p${blocks.length}`}>{bold(line)}</p>);
  }
  flush();
  return <div className="grid gap-2 text-[15px] leading-relaxed">{blocks}</div>;
}

export function AskYaad() {
  const { toast } = useToast();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setTurns(load()); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns]);

  const update = (id: string, patch: Partial<Turn>) =>
    setTurns(ts => { const next = ts.map(t => (t.id === id ? { ...t, ...patch } : t)); save(next); return next; });

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setText("");
    const temp = `t${Date.now()}`;
    setTurns(ts => [...ts, { id: temp, question: q, status: "pending" }]);
    try {
      const { data } = await api.post<{ id: string }>("/me/ask", { question: q });
      const started = Date.now();
      for (;;) {
        await new Promise(r => setTimeout(r, POLL_MS));
        const { data: job } = await api.get(`/me/ask/${data.id}`);
        if (job.status === "done") { update(temp, { status: "done", answer: job.answer, sources: job.sources }); break; }
        if (job.status === "failed") { update(temp, { status: "failed", error: job.error }); break; }
        if (Date.now() - started > GIVE_UP_MS) { update(temp, { status: "failed", error: "That took too long. Try again." }); break; }
      }
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      update(temp, { status: "failed", error: typeof detail === "string" ? detail : "Check your connection and try again." });
    } finally {
      setBusy(false);
    }
  };

  const copy = async (t: string) => {
    try { await navigator.clipboard.writeText(t); toast({ variant: "success", title: "Copied" }); }
    catch { toast({ variant: "error", title: "Couldn't copy", description: "Long-press the answer to copy it." }); }
  };

  return (
    <div className="mx-auto flex w-full max-w-[680px] flex-col">
      <div className="flex items-center gap-2">
        <AskBubble size={22} className="text-[var(--y-ink)]" aria-hidden />
        <h1 className="text-[24px] font-semibold tracking-[-0.02em]">Ask Yaad</h1>
      </div>
      <p className="mt-1 text-[14.5px] text-[var(--y-ink-2)]">Ask anything about your calls from the last 45 days.</p>

      <div className="mt-5 grid gap-5">
        {turns.map(t => (
          <div key={t.id} className="grid gap-2.5">
            <p className="max-w-[85%] justify-self-end rounded-[18px] rounded-br-md bg-[var(--y-brand)] px-4 py-2.5 text-[15px] text-[var(--y-on-brand)]">{t.question}</p>
            <div className="rounded-[18px] rounded-bl-md border border-[var(--y-line)] bg-[var(--y-card)] p-4 shadow-[var(--y-shadow)]">
              {t.status === "pending" && (
                <p className="flex items-center gap-2 text-[15px] text-[var(--y-ink-2)]"><Loader2 size={16} className="animate-spin" aria-hidden /> Reading your calls…</p>
              )}
              {t.status === "failed" && <p className="text-[15px] text-[var(--y-late)]">{t.error}</p>}
              {t.status === "done" && t.answer && (
                <>
                  <Formatted text={t.answer} />
                  {!!t.sources?.length && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {t.sources.map(s => (
                        <Link key={s.call_id} href={`/dashboard/me/calls/${s.call_id}`}
                          className="inline-flex min-h-8 max-w-full items-center gap-1 truncate rounded-full border border-[var(--y-line)] px-2.5 text-[12.5px] font-medium text-[var(--y-ink-2)] hover:border-[var(--y-line-strong)]">
                          <span className="truncate">{s.contact} · {dayLabel(istDay(new Date(s.at)))}</span>
                        </Link>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <a href={`https://wa.me/?text=${encodeURIComponent(t.answer)}`} target="_blank" rel="noopener noreferrer"
                      className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full bg-[var(--y-brand)] px-4 text-[14px] font-semibold text-[var(--y-on-brand)]">
                      <Send size={14} aria-hidden /> Share
                    </a>
                    <button type="button" onClick={() => copy(t.answer!)}
                      className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full border border-[var(--y-line-strong)] px-3.5 text-[14px] font-medium">
                      <Copy size={14} aria-hidden /> Copy
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className={cn("grid gap-2.5", turns.length ? "mt-6" : "mt-2")}>
        {!turns.length && <p className="text-[13px] font-semibold text-[var(--y-ink-2)]">Try</p>}
        <div className="flex flex-wrap gap-2">
          {PROMPTS.map(p => (
            <button key={p} type="button" disabled={busy} onClick={() => ask(p)}
              className="y-press min-h-11 rounded-full border border-[var(--y-line)] bg-[var(--y-card)] px-4 text-[14px] font-medium text-[var(--y-ink)] hover:border-[var(--y-line-strong)] disabled:opacity-50">
              {p}
            </button>
          ))}
        </div>
        <form className="mt-1 flex items-end gap-2" onSubmit={e => { e.preventDefault(); ask(text); }}>
          <label htmlFor="ask-yaad" className="sr-only">Your question</label>
          <textarea id="ask-yaad" rows={1} value={text} maxLength={500} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }}
            placeholder="Ask about your calls"
            className="min-h-12 flex-1 resize-none overflow-hidden rounded-[22px] border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 py-3 text-[16px] text-[var(--y-ink)] placeholder:text-[var(--y-ink-3)] focus:border-[var(--y-ink)] focus:outline-none" />
          <button type="submit" disabled={busy || !text.trim()} aria-label="Ask"
            className="y-press flex size-12 shrink-0 items-center justify-center rounded-full bg-[var(--y-brand)] text-[var(--y-on-brand)] disabled:opacity-40">
            {busy ? <Loader2 size={18} className="animate-spin" aria-hidden /> : <ArrowRight size={18} aria-hidden />}
          </button>
        </form>
      </div>
    </div>
  );
}
