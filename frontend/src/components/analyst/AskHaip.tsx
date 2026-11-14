"use client";
// Ask HAIP inside the AI Executive (owner): any business question in plain words. POST /analyst/ask-haip queues it, then
// GET /analyst/ask-haip/{id} is polled until the free-form analyst answers (KPI questions use the dashboards' own metric
// definitions; anything else is a validated, read-only, workspace-scoped query). Shows the answer, the rows it came
// from, and the query on request. The conversation is kept on this device only (a convenience, not a record).
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ArrowRight, Loader2, Sparkles } from "@/lib/icons";
import { Card, CardBody, CardHeader, EmptyState } from "@/components/ui/kit";

interface Turn {
  id: string;
  question: string;
  status: "pending" | "done" | "failed";
  narrative?: string;
  rows?: Record<string, unknown>[];
  row_count?: number;
  sql?: string | null;
  error?: string;
}

const STORE = "haip.askhaip.v1";
const POLL_MS = 2000;
const GIVE_UP_MS = 120_000;
const PROMPTS = [
  "How many new leads did we get this month, by source?",
  "Which source brought the most bookings last month?",
  "How many calls were missed this week?",
  "What was our revenue each month this year?",
];

function load(): Turn[] {
  try { return (JSON.parse(localStorage.getItem(STORE) ?? "[]") as Turn[]).filter(t => t.status !== "pending"); } catch { return []; }
}
function save(turns: Turn[]) {
  try { localStorage.setItem(STORE, JSON.stringify(turns.slice(-15))); } catch { /* private mode: memory only */ }
}

function cell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return v.toLocaleString("en-IN");
  return String(v);
}

function Rows({ rows, total }: { rows: Record<string, unknown>[]; total: number }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]).slice(0, 6);
  const shown = rows.slice(0, 12);
  return (
    <div className="mt-3">
      <div className="overflow-x-auto rounded-xl border border-[var(--haip-border)]">
        <table className="w-full min-w-[320px] text-left text-[13px] tabular-nums">
          <thead className="bg-[var(--haip-surface)] text-[var(--haip-fg-muted)]">
            <tr>{cols.map(c => <th key={c} scope="col" className="px-3 py-2 font-semibold">{c.replace(/_/g, " ")}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-[var(--haip-border)]">
            {shown.map((r, i) => <tr key={i}>{cols.map(c => <td key={c} className="px-3 py-2 text-[var(--haip-fg)]">{cell(r[c])}</td>)}</tr>)}
          </tbody>
        </table>
      </div>
      {total > shown.length && <p className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Showing {shown.length} of {total.toLocaleString("en-IN")} rows.</p>}
    </div>
  );
}

export function AskHaip() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const recent = useQuery<{ questions: { question: string }[] }>({
    queryKey: ["ask-haip-recent"],
    queryFn: () => api.get("/analyst/ask-haip/recent").then(r => r.data),
    staleTime: 60_000,
  });

  useEffect(() => { setTurns(load()); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [turns]);

  const update = (id: string, patch: Partial<Turn>) =>
    setTurns(ts => { const next = ts.map(t => (t.id === id ? { ...t, ...patch } : t)); save(next); return next; });

  const ask = async (question: string) => {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setText("");
    const temp = `t${Date.now()}`;
    setTurns(ts => [...ts, { id: temp, question: q, status: "pending" }]);
    try {
      const { data } = await api.post<{ id: string }>("/analyst/ask-haip", { question: q });
      const started = Date.now();
      for (;;) {
        await new Promise(r => setTimeout(r, POLL_MS));
        const { data: job } = await api.get(`/analyst/ask-haip/${data.id}`);
        if (job.status === "done") { update(temp, { ...job, id: temp, status: "done" }); break; }
        if (job.status === "failed") { update(temp, { status: "failed", error: job.error }); break; }
        if (Date.now() - started > GIVE_UP_MS) { update(temp, { status: "failed", error: "That took too long. Try again." }); break; }
      }
      recent.refetch();
    } catch (e) {
      const status = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
      const detail = typeof status?.data?.detail === "string" ? status.data.detail : null;
      update(temp, {
        status: "failed",
        error: status?.status === 403 ? "Ask HAIP is for the workspace owner, on plans that include it." : detail ?? "Check your connection and try again.",
      });
    } finally {
      setBusy(false);
    }
  };

  const suggestions = [...(recent.data?.questions.map(q => q.question) ?? []), ...PROMPTS].filter((q, i, a) => a.indexOf(q) === i).slice(0, 6);

  return (
    <Card>
      <CardHeader title="Ask HAIP" description="Ask anything about your leads, calls, bookings and revenue. Answers come from your live data." tone="plain" />
      <CardBody>
        {turns.length === 0 ? (
          <EmptyState title="Ask your first question" hint="Try one below, or type your own. Numbers match your dashboards." />
        ) : (
          <ul className="mb-4 space-y-4">
            {turns.map(t => (
              <li key={t.id} className="space-y-2">
                <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2 text-sm text-primary-foreground">{t.question}</p>
                <div className="rounded-2xl rounded-bl-md bg-[var(--haip-surface)] p-4 text-sm">
                  {t.status === "pending" && (
                    <p className="flex items-center gap-2 text-[var(--haip-fg-muted)]"><Loader2 size={16} className="animate-spin" aria-hidden /> Looking at your data…</p>
                  )}
                  {t.status === "failed" && <p className="text-[var(--haip-fg)]">{t.error}</p>}
                  {t.status === "done" && (
                    <>
                      <p className="flex gap-2 leading-relaxed text-[var(--haip-fg)]">
                        <Sparkles size={16} className="mt-0.5 shrink-0 text-primary" aria-hidden />
                        <span>{t.narrative}</span>
                      </p>
                      <Rows rows={t.rows ?? []} total={t.row_count ?? 0} />
                      {t.sql && !t.sql.startsWith("-- shared metrics") && (
                        <details className="mt-2 text-xs text-[var(--haip-fg-subtle)]">
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
        <div className="mb-3 flex flex-wrap gap-2">
          {suggestions.map(p => (
            <button key={p} type="button" disabled={busy} onClick={() => ask(p)}
              className="min-h-[44px] rounded-full border border-[var(--haip-border)] px-3 text-left text-[13px] font-medium text-[var(--haip-fg)] hover:border-primary disabled:opacity-50">
              {p}
            </button>
          ))}
        </div>
        <form className="flex gap-2" onSubmit={e => { e.preventDefault(); ask(text); }}>
          <label htmlFor="ask-haip" className="sr-only">Your question</label>
          <input id="ask-haip" value={text} onChange={e => setText(e.target.value)} maxLength={500} placeholder="Ask about your business"
            className="min-h-[44px] w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] outline-none focus-visible:ring-2 focus-visible:ring-primary sm:text-sm" />
          <button type="submit" aria-label="Ask" disabled={busy || text.trim().length < 3}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-primary px-4 text-primary-foreground disabled:opacity-60">
            {busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
          </button>
        </form>
      </CardBody>
    </Card>
  );
}
