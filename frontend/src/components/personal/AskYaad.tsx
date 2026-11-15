"use client";
// Ask Yaad: questions answered from your own calls (POST /me/ask, then poll GET /me/ask/{id}; the answer is written in
// the background). Answers cite their calls like Perplexity / ChatGPT: [n] chips that open the words said and play that
// moment, the sources listed under the answer, follow-up questions to tap, and a download as an editable PDF. Every
// question belongs to a chat (saved on the server, /me/asks); the history lists chats by day.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { ArrowRight, AskBubble, Copy, Delete, FileDown, History, Loader2, Plus, Send } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Drawer } from "@/components/ui/kit";
import { DOWNLOAD_TIMEOUT_MS, saveBlob, toBlob } from "@/lib/download";
import { chatGroup, dayLabel, istDay, momentHref, momentLabel, splitCites, withoutCites, type AskChat, type AskSource } from "@/lib/personal";
import { useAskChat, useAskChats, useAskSuggestions, useDeleteChat } from "./hooks";
import { SourceChip } from "./Cite";

type Stage = "sending" | "queued" | "reading" | "writing";
interface Turn {
  id: string; question: string; status: "pending" | "done" | "failed";
  stage?: Stage; calls?: number; answer?: string; error?: string;
  sources?: AskSource[]; followups?: string[]; turnId?: string;
}

const PROMPTS = ["Summarise today", "My action items", "What did I promise people?", "What's coming up this week?"];
const FOLDER_PROMPTS = ["Summarise this folder", "What is still open?", "What have I agreed to?", "Who is waiting on me?"];
const POLL_MS = 700;
const GIVE_UP_MS = 90_000;

/** The step the server reports (tasks personal.ask), so the wait reads as work, not a frozen screen. */
function stageText(stage: Stage | undefined, calls?: number): string {
  if (stage === "writing") return calls ? `Read ${calls} call${calls === 1 ? "" : "s"}. Writing your answer` : "Writing your answer";
  if (stage === "reading") return "Reading your calls";
  if (stage === "queued") return "Getting started";
  return "Sending";
}

function Thinking({ stage, calls }: { stage?: Stage; calls?: number }) {
  return (
    <p role="status" aria-live="polite" className="flex items-center gap-2.5 text-[15px] text-[var(--y-ink-2)]">
      <span className="flex items-center gap-1 text-[var(--y-brand)]" aria-hidden><span className="y-dot" /><span className="y-dot" /><span className="y-dot" /></span>
      <span key={stage} className="y-enter">{stageText(stage, calls)}…</span>
    </p>
  );
}

const sourceLabel = (s: AskSource) => [s.contact, s.at ? dayLabel(istDay(new Date(s.at))) : "", s.title].filter(Boolean).join(" · ");

/** *bold*, "* " list lines and [n] citations (the WhatsApp format the answers come in). Text only, never HTML. */
function Answer({ text, sources }: { text: string; sources: AskSource[] }) {
  const byN = new Map(sources.map(s => [s.n, s]));
  const cites = (part: string, key: string) => splitCites(part).map((p, i) => {
    if (typeof p === "string") return <span key={`${key}-${i}`}>{p}</span>;
    const s = byN.get(p);
    return s ? <SourceChip key={`${key}-${i}`} n={p} quote={s.quote} at={s.t} callId={s.call_id} label={sourceLabel(s)} /> : null;
  });
  const inline = (line: string, key: string) => line.split(/(\*[^*\n]+\*)/g).map((part, i) =>
    /^\*[^*\n]+\*$/.test(part) ? <strong key={`${key}b${i}`} className="font-semibold">{cites(part.slice(1, -1), `${key}b${i}`)}</strong> : cites(part, `${key}t${i}`));
  const blocks: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) blocks.push(<ul key={`l${blocks.length}`} className="grid list-disc gap-1 pl-5 marker:text-[var(--y-ink-3)]">{list.map((l, i) => <li key={i}>{inline(l, `l${blocks.length}-${i}`)}</li>)}</ul>);
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const item = line.match(/^\s*[*•-]\s+(.*)$/);
    if (item) { list.push(item[1]); continue; }
    flush();
    if (line.trim()) blocks.push(<p key={`p${blocks.length}`}>{inline(line, `p${blocks.length}`)}</p>);
  }
  flush();
  return <div className="grid gap-2 text-[15px] leading-relaxed">{blocks}</div>;
}

function Sources({ sources }: { sources: AskSource[] }) {
  return (
    <div className="mt-4 border-t border-[var(--y-line)] pt-3">
      <p className="mb-2 text-[12.5px] font-semibold text-[var(--y-ink-2)]">Sources</p>
      <ol className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
        {sources.map(s => (
          <li key={s.n}>
            <Link href={momentHref(s.call_id, s.t)}
              className="y-press flex min-h-11 items-start gap-2.5 rounded-[12px] px-2 py-1.5 hover:bg-[var(--y-canvas)]">
              <span className="mt-0.5 flex size-[18px] shrink-0 items-center justify-center rounded-full bg-[var(--y-soft)] text-[11px] font-bold text-[var(--y-soft-ink)]">{s.n}</span>
              <span className="min-w-0 flex-1 text-[13.5px] leading-snug">
                <span className="block truncate font-medium text-[var(--y-ink)]">{sourceLabel(s)}</span>
                {s.quote && <span className="line-clamp-2 italic text-[var(--y-ink-2)]">&ldquo;{s.quote}&rdquo;</span>}
              </span>
              {s.t != null && <span className="mt-0.5 shrink-0 text-[12px] font-semibold tabular-nums text-[var(--y-brand)]">{momentLabel(s.t)}</span>}
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** The person's chats, by day. `onPick(null)` = a new chat. */
function ChatHistory({ folderId, current, onPick }: { folderId?: string; current: string | null; onPick: (id: string | null) => void }) {
  const chats = useAskChats(folderId);
  const del = useDeleteChat();
  const { toast } = useToast();
  const [confirm, setConfirm] = useState<string | null>(null);
  const groups: [string, AskChat[]][] = [];
  for (const c of chats.data ?? []) {
    const g = chatGroup(c.updated_at);
    const last = groups[groups.length - 1];
    if (last && last[0] === g) last[1].push(c); else groups.push([g, [c]]);
  }
  return (
    <nav aria-label="Your chats" className="grid grid-cols-[minmax(0,1fr)] gap-3">
      <button type="button" onClick={() => onPick(null)}
        className="y-press inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 text-[14.5px] font-semibold">
        <Plus size={16} aria-hidden /> New chat
      </button>
      {chats.isPending && <div className="grid gap-2" aria-busy="true">{[0, 1, 2].map(i => <div key={i} className="h-9 animate-pulse rounded-lg bg-[var(--y-line)]" />)}</div>}
      {chats.isError && <p className="text-[13.5px] text-[var(--y-ink-2)]">Couldn&apos;t load your chats. <button type="button" className="underline" onClick={() => chats.refetch()}>Try again</button></p>}
      {chats.data && !chats.data.length && <p className="text-[13.5px] text-[var(--y-ink-2)]">Your questions and Yaad&apos;s answers are kept here.</p>}
      {groups.map(([g, items]) => (
        <div key={g}>
          <p className="mb-1 px-2 text-[12px] font-semibold text-[var(--y-ink-3)]">{g}</p>
          <ul className="grid grid-cols-[minmax(0,1fr)]">
            {items.map(c => (
              <li key={c.id} className="group flex items-center">
                <button type="button" onClick={() => onPick(c.id)} aria-current={c.id === current ? "true" : undefined}
                  className={cn("min-h-10 min-w-0 flex-1 truncate rounded-[10px] px-2 text-left text-[14px]",
                    c.id === current ? "bg-[var(--y-soft)] font-semibold text-[var(--y-soft-ink)]" : "text-[var(--y-ink)] hover:bg-[var(--y-canvas)]")}>
                  {c.title}
                </button>
                <button type="button"
                  aria-label={confirm === c.id ? `Confirm delete "${c.title}"` : `Delete "${c.title}"`}
                  onClick={() => {
                    if (confirm !== c.id) { setConfirm(c.id); return; }
                    del.mutate(c.id, {
                      onSuccess: () => { if (c.id === current) onPick(null); toast({ variant: "success", title: "Chat deleted" }); },
                      onError: () => toast({ variant: "error", title: "Couldn't delete it", description: "Try again." }),
                    });
                    setConfirm(null);
                  }}
                  className={cn("flex size-10 shrink-0 items-center justify-center rounded-full text-[var(--y-ink-3)] hover:text-[var(--y-late)]",
                    confirm === c.id ? "text-[var(--y-late)]" : "opacity-60 group-hover:opacity-100")}>
                  {confirm === c.id ? <span className="text-[12px] font-semibold">Delete?</span> : <Delete size={15} aria-hidden />}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** `compact`: inside a drawer or panel (no page heading, no side history). `folderId`: answers only from that folder's
 *  calls; its chats are listed apart. */
export function AskYaad({ compact = false, folderId }: { compact?: boolean; folderId?: string } = {}) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [chatId, setChatId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const loaded = useAskChat(chatId);
  const suggestions = useAskSuggestions(folderId);
  const loadedFor = useRef<string | null>(null);

  // An old chat picked from the history: its turns come from the server once (later turns are added here).
  useEffect(() => {
    const c = loaded.data;
    if (!c || loadedFor.current === c.id) return;
    loadedFor.current = c.id;
    setTurns((c.turns ?? []).map(t => ({ id: t.id, turnId: t.id, question: t.question, status: "done", answer: t.answer, sources: t.sources, followups: t.followups })));
  }, [loaded.data]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns.length]);

  const pick = (id: string | null) => {
    if (busy) return;
    loadedFor.current = null;
    setChatId(id);
    setTurns([]);
    setHistoryOpen(false);
  };
  const update = (id: string, patch: Partial<Turn>) => setTurns(ts => ts.map(t => (t.id === id ? { ...t, ...patch } : t)));

  const ask = async (question: string, retryOf?: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setText("");
    const temp = `t${Date.now()}`;
    setTurns(ts => [...ts.filter(t => t.id !== retryOf), { id: temp, question: q, status: "pending", stage: "sending" }]);
    try {
      const { data } = await api.post<{ id: string; session_id: string }>("/me/ask", {
        question: q, ...(folderId ? { folder_id: folderId } : {}), ...(chatId ? { session_id: chatId } : {}),
      });
      loadedFor.current = data.session_id;  // this chat's turns are already on screen
      setChatId(data.session_id);
      const started = Date.now();
      for (;;) {
        await new Promise(r => setTimeout(r, POLL_MS));
        const { data: job } = await api.get(`/me/ask/${data.id}`);
        if (job.status === "done") {
          update(temp, { status: "done", answer: job.answer, sources: job.sources, followups: job.followups, turnId: job.turn?.id });
          qc.invalidateQueries({ queryKey: ["me", "asks"] });
          break;
        }
        if (job.status === "failed") { update(temp, { status: "failed", error: job.error }); break; }
        setTurns(ts => ts.map(t => (t.id === temp ? { ...t, stage: job.stage ?? t.stage, calls: job.calls ?? t.calls } : t)));
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
  const pdf = async (turnId: string) => {
    try {
      const r = await api.get(`/me/asks/${chatId}/turns/${turnId}/pdf`, { responseType: "blob", timeout: DOWNLOAD_TIMEOUT_MS });
      await saveBlob(toBlob(r.data, "application/pdf"), `yaad-answer-${turnId}.pdf`);
    } catch {
      toast({ variant: "error", title: "Couldn't make the PDF", description: "Try again in a moment." });
    }
  };

  const lastDone = [...turns].reverse().find(t => t.status === "done")?.id;
  const starters = suggestions.data?.length ? suggestions.data : folderId ? FOLDER_PROMPTS : PROMPTS;
  const sideHistory = !compact;  // the Ask page: history beside the chat from lg, a drawer below

  const thread = (
    <div className="mx-auto flex w-full max-w-[680px] min-w-0 flex-col">
      <div className="flex items-center gap-2">
        {!compact && (
          <div className="flex items-center gap-2 max-md:sr-only">{/* phones: the top bar names the page */}
            <AskBubble size={22} className="text-[var(--y-ink)]" aria-hidden />
            <h1 className="text-[24px] font-semibold tracking-[-0.02em]">Ask Yaad</h1>
          </div>
        )}
        <div className={cn("ml-auto flex items-center gap-1", sideHistory && "lg:hidden")}>
          {turns.length > 0 && (
            <button type="button" onClick={() => pick(null)} disabled={busy}
              className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full px-3 text-[13.5px] font-semibold text-[var(--y-ink-2)] disabled:opacity-50">
              <Plus size={15} aria-hidden /> New
            </button>
          )}
          <button type="button" onClick={() => setHistoryOpen(true)}
            className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full border border-[var(--y-line)] px-3 text-[13.5px] font-semibold">
            <History size={15} aria-hidden /> History
          </button>
        </div>
      </div>
      {!compact && <p className="mt-1 text-[14.5px] text-[var(--y-ink-2)]">Ask anything about your calls. Every answer shows where it came from.</p>}
      {chatId && loaded.isPending && !turns.length && <div className="mt-5 h-24 animate-pulse rounded-[18px] bg-[var(--y-line)]" aria-busy="true" />}
      {chatId && loaded.isError && !turns.length && <p className="mt-5 text-[15px] text-[var(--y-ink-2)]">Couldn&apos;t open that chat. <button type="button" className="underline" onClick={() => loaded.refetch()}>Try again</button></p>}

      <div className="mt-5 grid grid-cols-[minmax(0,1fr)] gap-5">
        {turns.map(t => (
          <div key={t.id} className="y-enter grid grid-cols-[minmax(0,1fr)] gap-2.5">
            <p className="max-w-[85%] justify-self-end rounded-[18px] rounded-br-md bg-[var(--y-brand)] px-4 py-2.5 text-[15px] text-[var(--y-on-brand)]">{t.question}</p>
            <div className="min-w-0 rounded-[18px] rounded-bl-md border border-[var(--y-line)] bg-[var(--y-card)] p-4 shadow-[var(--y-shadow)]">
              {t.status === "pending" && <Thinking stage={t.stage} calls={t.calls} />}
              {t.status === "failed" && (
                <div className="y-enter grid justify-items-start gap-2">
                  <p className="text-[15px] text-[var(--y-late)]">{t.error}</p>
                  <button type="button" disabled={busy} onClick={() => ask(t.question, t.id)}
                    className="y-press inline-flex min-h-10 items-center rounded-full border border-[var(--y-line-strong)] px-3.5 text-[14px] font-medium disabled:opacity-50">
                    Try again
                  </button>
                </div>
              )}
              {t.status === "done" && t.answer && (
                <div className="y-enter">
                  <Answer text={t.answer} sources={t.sources ?? []} />
                  {!!t.sources?.length && <Sources sources={t.sources} />}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <a href={`https://wa.me/?text=${encodeURIComponent(withoutCites(t.answer))}`} target="_blank" rel="noopener noreferrer"
                      className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full bg-[var(--y-brand)] px-4 text-[14px] font-semibold text-[var(--y-on-brand)]">
                      <Send size={14} aria-hidden /> Share
                    </a>
                    <button type="button" onClick={() => copy(withoutCites(t.answer!))}
                      className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full border border-[var(--y-line-strong)] px-3.5 text-[14px] font-medium">
                      <Copy size={14} aria-hidden /> Copy
                    </button>
                    {t.turnId && chatId && (
                      <button type="button" onClick={() => pdf(t.turnId!)}
                        className="y-press inline-flex min-h-10 items-center gap-1.5 rounded-full border border-[var(--y-line-strong)] px-3.5 text-[14px] font-medium">
                        <FileDown size={14} aria-hidden /> PDF you can edit
                      </button>
                    )}
                  </div>
                  {t.id === lastDone && !busy && !!t.followups?.length && (
                    <div className="mt-4 grid gap-1.5">
                      <p className="text-[12.5px] font-semibold text-[var(--y-ink-2)]">Ask next</p>
                      {t.followups.map(f => (
                        <button key={f} type="button" onClick={() => ask(f)}
                          className="y-press flex min-h-11 items-center justify-between gap-2 rounded-[12px] border border-[var(--y-line)] px-3 text-left text-[14px] font-medium hover:border-[var(--y-line-strong)]">
                          {f} <ArrowRight size={14} className="shrink-0 text-[var(--y-ink-3)]" aria-hidden />
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className={cn("grid gap-2.5", turns.length ? "mt-6" : "mt-2")}>
        {!turns.length && !chatId && (
          <>
            <p className="text-[13px] font-semibold text-[var(--y-ink-2)]">Try</p>
            <div className="flex flex-wrap gap-2">
              {starters.map(p => (
                <button key={p} type="button" disabled={busy} onClick={() => ask(p)}
                  className="y-press min-h-11 rounded-full border border-[var(--y-line)] bg-[var(--y-card)] px-4 text-[14px] font-medium text-[var(--y-ink)] hover:border-[var(--y-line-strong)] disabled:opacity-50">
                  {p}
                </button>
              ))}
            </div>
          </>
        )}
        <form className="mt-1 flex items-end gap-2" onSubmit={e => { e.preventDefault(); ask(text); }}>
          <label htmlFor={`ask-yaad-${compact ? "c" : "p"}`} className="sr-only">Your question</label>
          <textarea id={`ask-yaad-${compact ? "c" : "p"}`} rows={1} value={text} maxLength={500} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }}
            placeholder={turns.length ? "Ask a follow-up" : folderId ? "Ask about this folder" : "Ask about your calls"}
            className="min-h-12 flex-1 resize-none overflow-hidden rounded-[22px] border border-[var(--y-line-strong)] bg-[var(--y-card)] px-4 py-3 text-[16px] text-[var(--y-ink)] placeholder:text-[var(--y-ink-3)] focus:border-[var(--y-ink)] focus:outline-none" />
          <button type="submit" disabled={busy || !text.trim()} aria-label="Ask"
            className="y-press flex size-12 shrink-0 items-center justify-center rounded-full bg-[var(--y-brand)] text-[var(--y-on-brand)] disabled:opacity-40">
            {busy ? <Loader2 size={18} className="animate-spin" aria-hidden /> : <ArrowRight size={18} aria-hidden />}
          </button>
        </form>
      </div>

      <Drawer open={historyOpen} onOpenChange={setHistoryOpen} title="Your chats" className="yaad">
        <ChatHistory folderId={folderId} current={chatId} onPick={pick} />
      </Drawer>
    </div>
  );

  if (!sideHistory) return thread;
  return (
    <div className="lg:grid lg:grid-cols-[240px_minmax(0,1fr)] lg:items-start lg:gap-8">
      <aside className="sticky top-0 hidden max-h-[calc(100dvh-6rem)] overflow-y-auto lg:block">
        <ChatHistory folderId={folderId} current={chatId} onPick={pick} />
      </aside>
      {thread}
    </div>
  );
}
