"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Sparkles, Send, Loader2, Code2, ChevronDown, ChevronUp, ShieldAlert } from "@/lib/icons";
import api from "@/lib/api";
import { AgentChart, type ChartSpec } from "@/components/ask-haip/AgentChart";

interface FreeformResult {
  narrative: string | null;
  error: string | null;
  chart: ChartSpec | null;
  rows: Record<string, unknown>[];
  row_count: number;
  sql: string | null;
}

const EXAMPLES = [
  "How many inquiries do we have by stage?",
  "Which guests have the highest lifetime value?",
  "How many calls did we get in the last 7 days?",
  "Show me confirmed stays sorted by check-in date",
];

export default function FreeformAnalystPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const role = session?.user?.role;

  const [question, setQuestion] = useState("");
  const [visibleSql, setVisibleSql] = useState<Set<number>>(new Set());
  const [history, setHistory] = useState<{ question: string; result: FreeformResult }[]>([]);

  const ask = useMutation({
    mutationFn: (q: string) =>
      api.post<FreeformResult>("/analytics/ask/freeform", { question: q }).then(r => r.data),
    onSuccess: (result, q) => {
      setHistory(h => [{ question: q, result }, ...h]);
      setQuestion("");
    },
  });

  function toggleSql(i: number) {
    setVisibleSql(s => {
      const next = new Set(s);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });
  }

  function submit() {
    const q = question.trim();
    if (!q || ask.isPending) return;
    ask.mutate(q);
  }

  // Backend already enforces this (403), but no point showing a form that
  // can never succeed -- Phase 2 of the build plan is explicitly Owner-only.
  if (role && role !== "owner") {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-center px-6 bg-[#F8FAFC]">
        <ShieldAlert size={32} className="text-gray-300" />
        <p className="text-sm font-semibold text-gray-600">Owner access only</p>
        <p className="text-xs text-gray-400 max-w-xs">
          The free-form analyst is in an early access phase, available to account owners only.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      <div className="flex-shrink-0 px-6 py-3 flex items-center justify-between" style={{ background: "#FFFFFF", borderBottom: "1px solid #E5E7EB" }}>
        <div>
          <h1 className="text-base font-bold flex items-center gap-2" style={{ fontFamily: "var(--font-display), sans-serif", color: "#111827" }}>
            <Sparkles size={16} className="text-teal-600" /> Free-Form Analyst
          </h1>
          <p className="text-xs mt-0.5 text-gray-500">Ask anything about your data — early access, Owner only</p>
        </div>
        <button
          onClick={() => router.push("/dashboard/ask-haip")}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold"
          style={{ border: "1px solid #0F766E", color: "#0F766E" }}
        >
          Back to Ask HAIP
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto space-y-5">
          {/* Question input */}
          <div className="bg-white rounded-2xl border p-4" style={{ borderColor: "#E5E7EB" }}>
            <textarea
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
              placeholder="Ask a question about your leads, guests, calls, bookings…"
              rows={2}
              className="w-full text-sm outline-none resize-none"
            />
            <div className="flex items-center justify-between mt-2">
              <div className="flex flex-wrap gap-1.5">
                {EXAMPLES.map(ex => (
                  <button
                    key={ex}
                    onClick={() => setQuestion(ex)}
                    className="text-[10.5px] px-2 py-1 rounded-full bg-gray-100 text-gray-500 hover:bg-gray-200 transition-colors"
                  >
                    {ex}
                  </button>
                ))}
              </div>
              <button
                onClick={submit}
                disabled={!question.trim() || ask.isPending}
                className="flex-shrink-0 flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white disabled:opacity-40 transition-colors"
                style={{ background: "#0F766E" }}
              >
                {ask.isPending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                Ask
              </button>
            </div>
          </div>

          {/* Results (newest first) */}
          {history.map((h, i) => (
            <div key={i} className="bg-white rounded-2xl border p-5" style={{ borderColor: "#E5E7EB" }}>
              <p className="text-[11px] font-semibold text-gray-400 mb-2">{h.question}</p>

              {h.result.error ? (
                <p className="text-sm text-red-600">{h.result.error}</p>
              ) : (
                <>
                  <p className="text-[13.5px] text-gray-800 leading-relaxed mb-3">{h.result.narrative}</p>

                  {h.result.chart && (
                    <div className="mb-3">
                      <AgentChart spec={h.result.chart} />
                    </div>
                  )}

                  {h.result.rows.length > 0 && (
                    <div className="overflow-x-auto rounded-xl border mb-2" style={{ borderColor: "#F3F4F6" }}>
                      <table className="w-full text-left text-[11.5px]">
                        <thead>
                          <tr style={{ background: "#F8FAFC" }}>
                            {Object.keys(h.result.rows[0]).map(col => (
                              <th key={col} className="px-3 py-2 font-semibold text-gray-500 uppercase text-[9.5px] tracking-wide">{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {h.result.rows.slice(0, 20).map((row, ri) => (
                            <tr key={ri} className="border-t" style={{ borderColor: "#F3F4F6" }}>
                              {Object.values(row).map((v, ci) => (
                                <td key={ci} className="px-3 py-2 text-gray-700">{String(v ?? "—")}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <p className="text-[10px] text-gray-400 mb-1">{h.result.row_count} row{h.result.row_count !== 1 ? "s" : ""}</p>

                  {h.result.sql && (
                    <div>
                      <button
                        onClick={() => toggleSql(i)}
                        className="flex items-center gap-1 text-[10.5px] text-gray-400 hover:text-gray-600"
                      >
                        <Code2 size={11} /> View SQL {visibleSql.has(i) ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                      </button>
                      {visibleSql.has(i) && (
                        <pre className="mt-1.5 p-2.5 rounded-lg bg-gray-50 text-[10.5px] text-gray-600 overflow-x-auto">{h.result.sql}</pre>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}

          {history.length === 0 && !ask.isPending && (
            <p className="text-center text-xs text-gray-400 pt-8">
              Ask any question about your leads, guests, calls, or bookings — try one of the examples above.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
