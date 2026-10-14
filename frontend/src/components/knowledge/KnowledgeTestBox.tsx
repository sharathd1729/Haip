"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Loader2, Search, Sparkles } from "@/lib/icons";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { StatusPill } from "@/components/ui/kit";

interface Flag { code: string; severity: "info" | "warn" | "block"; message: string }
interface Hit { id: string; category: string; question?: string | null; content: string; score: number; property_id?: string | null }
interface Source { kind: string; key: string; version: number }
interface QuoteLine { label: string; amount: string; detail?: string }
interface TestResult {
  kb: { status: string; retrievable_count: number; hits: Hit[] };
  structured: {
    matched_package: string | null;
    sources: Source[];
    quote: null | { reason?: string; refused?: string; message?: string; lines?: QuoteLine[]; subtotal?: string; gst?: string; total?: string; advance?: string; valid_until?: string; package_name?: string };
    quote_sources: Source[];
  };
  flags: Flag[];
  ai_sees_prices: boolean;
}

const SEVERITY: Record<Flag["severity"], { tone: "danger" | "warning" | "info"; word: string }> = {
  block: { tone: "danger", word: "Blocks an answer" },
  warn: { tone: "warning", word: "Check" },
  info: { tone: "info", word: "Note" },
};
const money = (v?: string) => (v == null ? "—" : formatINR(Number(v)));
const INPUT = "min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base focus:outline-none focus:ring-2 focus:ring-primary/30 sm:min-h-9 sm:text-[13px]";

export function KnowledgeTestBox({ properties }: { properties: { id: string; name: string }[] }) {
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [property, setProperty] = useState("");
  const [more, setMore] = useState(false);
  const [d, setD] = useState({ destination: "", check_in: "", check_out: "", adults: "", children: "" });
  const [result, setResult] = useState<TestResult | null>(null);

  const run = useMutation({
    mutationFn: () => {
      const details: Record<string, unknown> = {};
      if (d.destination.trim()) details.destination = d.destination.trim();
      if (d.check_in && d.check_out) { details.check_in = d.check_in; details.check_out = d.check_out; }
      if (d.adults) details.adults = Number(d.adults);
      if (d.children) details.children = Number(d.children);
      return api.post("/knowledge/test", { query, top_k: 5, ...(property ? { property_id: property } : {}), details }).then(r => r.data as TestResult);
    },
    onSuccess: setResult,
    onError: () => toast({ variant: "error", title: "The test failed", description: "Try again in a minute." }),
  });
  const go = () => query.trim() && run.mutate();
  const q = result?.structured.quote;

  return (
    <section aria-labelledby="kb-test-title" className="rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-4 shadow-sm sm:p-5">
      <div className="mb-1 flex items-center gap-1.5">
        <Sparkles size={14} className="text-primary" />
        <h2 id="kb-test-title" className="text-sm font-semibold text-[var(--haip-fg)]">Test what the AI knows</h2>
      </div>
      <p className="mb-3 text-xs text-[var(--haip-fg-subtle)]">
        Runs the same lookups the AI runs before it replies: your knowledge entries and your published packages, routes, rules and quote. Drafts are never used.
      </p>
      <div className="flex flex-wrap gap-2">
        {properties.length > 1 && (
          <select value={property} onChange={e => setProperty(e.target.value)} aria-label="Property to test for" className={`${INPUT} sm:w-auto`}>
            <option value="">Any property</option>
            {properties.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        )}
        <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === "Enter") go(); }}
          placeholder="e.g. What does the Coorg trip cost for 2 nights?" aria-label="Guest question" className={`${INPUT} flex-1`} />
        <button onClick={go} disabled={run.isPending || !query.trim()}
          className="flex min-h-11 items-center gap-1.5 rounded-lg bg-primary px-4 text-xs font-semibold text-primary-foreground disabled:opacity-50 sm:min-h-9">
          {run.isPending ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />} Test
        </button>
      </div>
      <button onClick={() => setMore(m => !m)} aria-expanded={more} className="mt-2 min-h-9 text-xs font-semibold text-primary">
        {more ? "Hide" : "Add"} what the guest has said (dates, party, destination)
      </button>
      {more && (
        <div className="mt-2 grid gap-2 sm:grid-cols-5">
          <input aria-label="Destination" placeholder="Destination" value={d.destination} onChange={e => setD({ ...d, destination: e.target.value })} className={`${INPUT} sm:col-span-2`} />
          <input aria-label="Check-in" type="date" value={d.check_in} onChange={e => setD({ ...d, check_in: e.target.value })} className={INPUT} />
          <input aria-label="Check-out" type="date" value={d.check_out} onChange={e => setD({ ...d, check_out: e.target.value })} className={INPUT} />
          <div className="flex gap-2">
            <input aria-label="Adults" placeholder="Adults" inputMode="numeric" value={d.adults} onChange={e => setD({ ...d, adults: e.target.value.replace(/\D/g, "") })} className={INPUT} />
            <input aria-label="Children" placeholder="Kids" inputMode="numeric" value={d.children} onChange={e => setD({ ...d, children: e.target.value.replace(/\D/g, "") })} className={INPUT} />
          </div>
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-4" aria-live="polite">
          {result.flags.length > 0 && (
            <ul className="space-y-1.5">
              {result.flags.map((f, i) => (
                <li key={`${f.code}-${i}`} className="flex flex-wrap items-start gap-2 text-xs">
                  <StatusPill tone={SEVERITY[f.severity].tone}>{SEVERITY[f.severity].word}</StatusPill>
                  <span className="min-w-0 flex-1 break-words text-[var(--haip-fg-2)]">{f.message}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="space-y-1.5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--haip-fg-subtle)]">Exact data (published)</h3>
            {result.structured.matched_package ? (
              <p className="text-xs text-[var(--haip-fg-2)]">Package identified: <strong>{result.structured.matched_package}</strong></p>
            ) : (
              <p className="text-xs text-[var(--haip-fg-subtle)]">No single package identified from what was stated.</p>
            )}
            {q && !q.refused && (
              <div className="overflow-x-auto rounded-xl border border-[var(--haip-border)]">
                <table className="w-full text-xs tabular-nums">
                  <tbody>
                    {q.lines?.map(l => (
                      <tr key={l.label} className="border-b border-[var(--haip-border)] last:border-0">
                        <td className="px-3 py-1.5">{l.label}<span className="block text-[11px] text-[var(--haip-fg-subtle)]">{l.detail}</span></td>
                        <td className="px-3 py-1.5 text-right">{money(l.amount)}</td>
                      </tr>
                    ))}
                    <tr className="bg-[var(--haip-surface)] font-semibold"><td className="px-3 py-1.5">GST {money(q.gst)} · Total</td><td className="px-3 py-1.5 text-right">{money(q.total)}</td></tr>
                    {q.advance && <tr><td className="px-3 py-1.5">Advance</td><td className="px-3 py-1.5 text-right">{money(q.advance)}</td></tr>}
                  </tbody>
                </table>
              </div>
            )}
            {q?.refused && (
              <div className="flex items-start gap-2 rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] p-3 text-xs text-[var(--haip-status-warning-fg)]">
                <AlertCircle size={14} className="mt-0.5 shrink-0" /> No price: {q.message}
              </div>
            )}
            {result.structured.sources.length > 0 && (
              <p className="text-[11px] leading-relaxed text-[var(--haip-fg-subtle)]">
                Sources: {result.structured.sources.map(s => `${s.kind} “${s.key}” v${s.version}`).join(" · ")}
              </p>
            )}
            <p className="text-[11px] text-[var(--haip-fg-subtle)]">
              {result.ai_sees_prices ? "The AI may repeat the prices above and no others." : "Prices are shown here for you only — in hand-off mode the AI never states one."}
            </p>
          </div>

          <div className="space-y-1.5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--haip-fg-subtle)]">Knowledge entries ({result.kb.retrievable_count} usable)</h3>
            {result.kb.hits.length === 0 ? (
              <p className="text-xs text-[var(--haip-fg-subtle)]">Nothing matched.</p>
            ) : result.kb.hits.map(h => (
              <div key={h.id} className="rounded-lg border border-[var(--haip-border)] bg-[var(--haip-surface)] p-3">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-primary">{h.category} · match {(h.score * 100).toFixed(0)}%</p>
                {h.question && <p className="text-xs font-medium text-[var(--haip-fg-2)]">{h.question}</p>}
                <p className="text-xs leading-relaxed text-[var(--haip-fg-subtle)]">{h.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
