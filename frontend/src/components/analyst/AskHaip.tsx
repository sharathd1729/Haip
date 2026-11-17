"use client";
// Ask HAIP (owner): any business question in plain words, rebuilt like Ask Yaad (workspace redesign Phase 3). POST
// /analyst/ask-haip {question, session_id} queues it, GET /analyst/ask-haip/{id} is polled until the analyst answers (KPI
// questions use the dashboards' own definitions; anything else a validated, read-only, workspace-scoped query). Chats are
// kept on the server (GET /analyst/ask-haip/history, last 30 days, by day). Each answer says where it came from, rows that
// are a record open it, and suggests what to ask next. `compact` = the floating panel (components/shell/AskHaipLauncher).
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowRight, History, Loader2, Plus, Sparkles } from "@/lib/icons";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";

interface Turn {
  id: string;
  question: string;
  status: "pending" | "done" | "failed";
  narrative?: string | null;
  rows?: Record<string, unknown>[];
  row_count?: number | null;
  sql?: string | null;
  error?: string;
  source?: { label: string; shared_metrics: boolean; row_count: number };
  followups?: string[];
  fromHistory?: boolean;
}
interface Chat { id: string; title: string; last_at: string | null; turns: { question: string; narrative: string | null; status: string; row_count: number | null; at: string | null }[] }

const POLL_MS = 2000;
const GIVE_UP_MS = 120_000;
export const ASK_PROMPTS = [
  "How many new leads did we get this month, by source?",
  "Which source brought the most bookings last month?",
  "How many calls were missed this week?",
  "What was our revenue each month this year?",
];

function cell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return v.toLocaleString("en-IN");
  return String(v);
}

function dayLabel(iso: string | null): string {
  if (!iso) return "Earlier";
  const d = new Date(iso), today = new Date();
  const diff = Math.round((new Date(today.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86400000);
  return diff === 0 ? "Today" : diff === 1 ? "Yesterday" : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function Rows({ rows, total }: { rows: Record<string, unknown>[]; total: number }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]).filter(c => c !== "_href" && c !== "id").slice(0, 6);
  const shown = rows.slice(0, 12);
  const linked = shown.some(r => typeof r._href === "string");
  return (
    <div className="mt-3">
      <div className="overflow-x-auto rounded-xl border border-[var(--haip-border)]">
        <table className="w-full min-w-[320px] text-left text-[13px] tabular-nums">
          <thead className="bg-[var(--haip-surface)] text-[var(--haip-fg-muted)]">
            <tr>{cols.map(c => <th key={c} scope="col" className="px-3 py-2 font-semibold">{c.replace(/_/g, " ")}</th>)}{linked && <th className="px-3 py-2"><span className="sr-only">Open</span></th>}</tr>
          </thead>
          <tbody className="divide-y divide-[var(--haip-border)]">
            {shown.map((r, i) => (
              <tr key={i}>
                {cols.map(c => <td key={c} className="px-3 py-2 text-[var(--haip-fg)]">{cell(r[c])}</td>)}
                {linked && <td className="px-3 py-2 text-right">{typeof r._href === "string" && <Link href={r._href} className="font-semibold text-primary hover:underline">Open</Link>}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > shown.length && <p className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Showing {shown.length} of {total.toLocaleString("en-IN")} rows.</p>}
    </div>
  );
}

export function AskHaip({ initialQuestion, compact = false, prompts = ASK_PROMPTS }: { initialQuestion?: string; compact?: boolean; prompts?: string[] } = {}) {
  const qc = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [showChats, setShowChats] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const history = useQuery<{ chats: Chat[] }>({
    queryKey: ["ask-haip-history"], queryFn: () => api.get("/analyst/ask-haip/history").then(r => r.data), staleTime: 30_000,
  });

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [turns]);

  const update = (id: string, patch: Partial<Turn>) => setTurns(ts => ts.map(t => (t.id === id ? { ...t, ...patch } : t)));

  const ask = async (question: string) => {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setText("");
    const temp = `t${Date.now()}`;
    setTurns(ts => [...ts, { id: temp, question: q, status: "pending" }]);
    try {
      const { data } = await api.post<{ id: string; session_id: string }>("/analyst/ask-haip", { question: q, ...(sessionId ? { session_id: sessionId } : {}) });
      setSessionId(data.session_id);
      const started = Date.now();
      for (;;) {
        await new Promise(r => setTimeout(r, POLL_MS));
        const { data: job } = await api.get(`/analyst/ask-haip/${data.id}`);
        if (job.status === "done") { update(temp, { ...job, id: temp, status: "done" }); break; }
        if (job.status === "failed") { update(temp, { status: "failed", error: job.error }); break; }
        if (Date.now() - started > GIVE_UP_MS) { update(temp, { status: "failed", error: "That took too long. Try again." }); break; }
      }
      qc.invalidateQueries({ queryKey: ["ask-haip-history"] });
    } catch (e) {
      const res = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
      const detail = typeof res?.data?.detail === "string" ? res.data.detail : null;
      update(temp, { status: "failed",
        error: res?.status === 403 ? "Ask HAIP is for the workspace owner, on plans that include it." : detail ?? "Check your connection and try again." });
    } finally {
      setBusy(false);
    }
  };

  // A question typed in the command bar (?q=) is asked once on arrival.
  const askedInitial = useRef(false);
  useEffect(() => {
    if (!initialQuestion || askedInitial.current) return;
    askedInitial.current = true;
    void ask(initialQuestion);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per arrival
  }, [initialQuestion]);

  const openChat = (c: Chat) => {
    setSessionId(c.id);
    setTurns(c.turns.map((t, i) => ({ id: `${c.id}-${i}`, question: t.question, fromHistory: true,
      status: t.status === "ok" ? "done" : "failed", narrative: t.narrative, row_count: t.row_count,
      error: t.status === "ok" ? undefined : "HAIP couldn't answer this one." })));
    setShowChats(false);
  };
  const newChat = () => { setSessionId(null); setTurns([]); setShowChats(false); };

  const chats = history.data?.chats ?? [];
  const groups: [string, Chat[]][] = [];
  for (const c of chats) {
    const label = dayLabel(c.last_at);
    const g = groups.find(([l]) => l === label);
    if (g) g[1].push(c); else groups.push([label, [c]]);
  }
  const last = turns[turns.length - 1];
  const next = last?.status === "done" && last.followups?.length ? last.followups : prompts.slice(0, compact ? 3 : 6);

  const chatList = (
    <nav aria-label="Ask HAIP chats" className="space-y-3">
      <button type="button" onClick={newChat} className="flex min-h-11 w-full items-center gap-2 rounded-xl border border-[var(--haip-border)] px-3 text-sm font-semibold text-primary hover:bg-[var(--haip-surface)]">
        <Plus size={15} /> New chat
      </button>
      {history.isPending ? <p className="px-1 text-xs text-[var(--haip-fg-subtle)]">Loading chats…</p>
        : history.isError ? <p className="px-1 text-xs text-[var(--haip-fg-subtle)]">Couldn&apos;t load your chats. <button type="button" onClick={() => history.refetch()} className="font-semibold text-primary hover:underline">Try again</button></p>
        : groups.length === 0 ? <p className="px-1 text-xs text-[var(--haip-fg-subtle)]">Your chats from the last 30 days show here.</p>
        : groups.map(([label, list]) => (
          <div key={label}>
            <p className="px-1 pb-1 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{label}</p>
            {list.map(c => (
              <button key={c.id} type="button" onClick={() => openChat(c)} aria-current={c.id === sessionId ? "true" : undefined}
                className={cn("block min-h-10 w-full truncate rounded-lg px-2 text-left text-[13px]",
                  c.id === sessionId ? "bg-[var(--haip-nav-active-bg)] font-semibold text-[var(--haip-nav-active-fg)]" : "text-[var(--haip-fg)] hover:bg-[var(--haip-surface)]")}>
                {c.title}
              </button>
            ))}
          </div>
        ))}
    </nav>
  );

  const conversation = (
    <div className="min-w-0 flex-1">
      {compact && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <button type="button" onClick={() => setShowChats(s => !s)} aria-expanded={showChats}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-2 text-[13px] font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
            <History size={15} /> Chats
          </button>
          <button type="button" onClick={newChat} className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-2 text-[13px] font-semibold text-primary hover:bg-[var(--haip-surface)]">
            <Plus size={15} /> New chat
          </button>
        </div>
      )}
      {compact && showChats && <div className="mb-4 rounded-xl border border-[var(--haip-border)] p-3">{chatList}</div>}
      {turns.length === 0 ? (
        <EmptyState title="Ask about your business" hint="Leads, calls, bookings and revenue. Numbers match your dashboards." />
      ) : (
        <ul className="mb-4 space-y-4">
          {turns.map(t => (
            <li key={t.id} className="space-y-2">
              <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2 text-sm text-primary-foreground">{t.question}</p>
              <div className="rounded-2xl rounded-bl-md bg-[var(--haip-surface)] p-4 text-sm">
                {t.status === "pending" && <p className="flex items-center gap-2 text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" aria-hidden /> Looking at your data…</p>}
                {t.status === "failed" && <p className="text-[var(--haip-fg)]">{t.error}</p>}
                {t.status === "done" && (
                  <>
                    <p className="flex gap-2 leading-relaxed text-[var(--haip-fg)]"><Sparkles size={16} className="mt-0.5 shrink-0 text-primary" aria-hidden /><span>{t.narrative}</span></p>
                    <Rows rows={t.rows ?? []} total={t.row_count ?? 0} />
                    <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">
                      {t.source ? `From: ${t.source.label}${t.source.shared_metrics ? " (the dashboards' own definitions)" : ""} · ${t.source.row_count.toLocaleString("en-IN")} rows`
                        : t.fromHistory ? `Earlier answer${t.row_count != null ? ` · ${t.row_count} rows` : ""}. Ask again to see the rows.` : null}
                    </p>
                    {t.sql && !t.sql.startsWith("-- shared metrics") && (
                      <details className="mt-1 text-xs text-[var(--haip-fg-subtle)]">
                        <summary className="min-h-[32px] cursor-pointer py-1">How HAIP got this</summary>
                        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded-lg bg-[var(--haip-card)] p-2 font-mono">{t.sql}</pre>
                      </details>
                    )}
                  </>
                )}
              </div>
            </li>
          ))}
          <div ref={endRef} />
        </ul>
      )}
      <p className="mb-1.5 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{last?.status === "done" && last.followups?.length ? "Ask next" : "Try"}</p>
      <div className="mb-3 flex flex-wrap gap-2">
        {next.map(p => (
          <button key={p} type="button" disabled={busy} onClick={() => ask(p)}
            className="min-h-[44px] rounded-full border border-[var(--haip-border)] px-3 text-left text-[13px] font-medium text-[var(--haip-fg)] hover:border-primary disabled:opacity-50">
            {p}
          </button>
        ))}
      </div>
      <form className="flex gap-2" onSubmit={e => { e.preventDefault(); ask(text); }}>
        <label htmlFor={compact ? "ask-haip-panel" : "ask-haip"} className="sr-only">Your question</label>
        <input id={compact ? "ask-haip-panel" : "ask-haip"} value={text} onChange={e => setText(e.target.value)} maxLength={500} placeholder="Ask about your business"
          className="min-h-[44px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-sm" />
        <button type="submit" aria-label="Ask" disabled={busy || text.trim().length < 3}
          className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-primary px-4 text-primary-foreground disabled:opacity-60">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
        </button>
      </form>
    </div>
  );

  if (compact) return conversation;
  return (
    <Card>
      <CardHeader title="Ask HAIP" description="Ask anything about your leads, calls, bookings and revenue. Answers come from your live data." tone="plain" />
      <CardBody>
        <div className="flex flex-col gap-6 lg:flex-row">
          <aside className="lg:w-60 lg:shrink-0">{chatList}</aside>
          {conversation}
        </div>
      </CardBody>
    </Card>
  );
}
