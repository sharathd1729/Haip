"use client";
// Instagram welcome questions (before someone's first message) and the chat menu (GET/PUT /instagram/welcome).
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { Drawer } from "@/components/ui/kit";
import type { IgRule } from "./automationTypes";

type Question = { question: string; rule_id: string | null };
type MenuItem = { title: string; kind: "automation" | "link" | "message"; rule_id?: string | null; url?: string | null };
type Welcome = { questions: Question[]; menu: MenuItem[] };

const field = "min-h-11 w-full rounded-[12px] border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] sm:text-[14.5px] text-[var(--haip-fg)] placeholder:text-[var(--haip-fg-subtle)] focus:border-primary focus:outline-none";
const iconBtn = "flex size-11 shrink-0 items-center justify-center rounded-full border border-[var(--haip-border)]";

export function WelcomeSettings({ open, onOpenChange, rules }: { open: boolean; onOpenChange: (o: boolean) => void; rules: IgRule[] }) {
  const q = useQuery<Welcome>({ queryKey: ["ig-welcome"], queryFn: () => api.get("/instagram/welcome").then(r => r.data), enabled: open });
  const [w, setW] = useState<Welcome>({ questions: [], menu: [] });
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (q.data) setW(q.data); }, [q.data]);

  const save = useMutation({
    mutationFn: () => api.put("/instagram/welcome", {
      questions: w.questions.filter(x => x.question.trim()).map(x => ({ question: x.question.trim(), rule_id: x.rule_id || null })),
      menu: w.menu.filter(m => m.title.trim()).map(m => ({ title: m.title.trim(), kind: m.kind, rule_id: m.kind === "automation" ? m.rule_id : null, url: m.kind === "link" ? (m.url ?? "").trim() : null })),
    }).then(r => r.data as { pushed: boolean; error: string | null }),
    onSuccess: d => setResult(d.pushed ? { ok: true, text: "Saved and live on Instagram." } : { ok: false, text: `Saved, but Instagram didn't accept it: ${d.error ?? "unknown reason"}. Reconnecting Instagram usually fixes this.` }),
    onError: (e: { response?: { data?: { detail?: string } } }) => setResult({ ok: false, text: e?.response?.data?.detail || "Couldn't save. Check the fields and try again." }),
  });

  const ruleOptions = rules.map(r => <option key={r.id} value={r.id}>{r.name}</option>);
  const setQ = (i: number, patch: Partial<Question>) => setW({ ...w, questions: w.questions.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const setM = (i: number, patch: Partial<MenuItem>) => setW({ ...w, menu: w.menu.map((x, j) => (j === i ? { ...x, ...patch } : x)) });

  return (
    <Drawer open={open} onOpenChange={onOpenChange} title="Welcome questions and chat menu"
      description="Shown to people in your Instagram chats. Each one can run an automation, or be answered like a normal message."
      footer={
        <div className="flex w-full flex-col gap-2">
          {result && <p role="status" className={result.ok ? "text-[13.5px] text-primary" : "text-[13.5px] text-[var(--haip-status-danger-fg)]"}>{result.text}</p>}
          <button type="button" onClick={() => { setResult(null); save.mutate(); }} disabled={save.isPending || q.isLoading}
            className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-primary text-[14.5px] font-semibold text-primary-foreground transition-transform active:scale-[0.97] disabled:opacity-60">
            {save.isPending && <Loader2 size={15} className="animate-spin" />} Save and publish
          </button>
        </div>
      }>
      {q.isLoading ? (
        <div className="grid gap-3" aria-busy="true">{[0, 1, 2].map(i => <div key={i} className="h-14 animate-pulse rounded-[12px] bg-[var(--haip-surface)]" />)}</div>
      ) : q.isError ? (
        <p className="text-[14px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t load these settings. Close and try again.</p>
      ) : (
        <div className="grid gap-6">
          <section>
            <h3 className="text-[14.5px] font-semibold">Welcome questions</h3>
            <p className="mt-0.5 text-[13px] text-[var(--haip-fg-subtle)]">Up to 4. Instagram shows them before someone sends their first message.</p>
            <div className="mt-3 grid gap-3">
              {w.questions.map((x, i) => (
                <div key={i} className="grid gap-2 rounded-[14px] border border-[var(--haip-border)] p-3">
                  <div className="flex gap-2">
                    <input className={field} value={x.question} maxLength={80} placeholder="What are your prices?" onChange={e => setQ(i, { question: e.target.value })} aria-label={`Question ${i + 1}`} />
                    <button type="button" className={iconBtn} aria-label={`Remove question ${i + 1}`} onClick={() => setW({ ...w, questions: w.questions.filter((_, j) => j !== i) })}><Trash2 size={15} /></button>
                  </div>
                  <select className={field} value={x.rule_id ?? ""} onChange={e => setQ(i, { rule_id: e.target.value || null })} aria-label={`What question ${i + 1} does`}>
                    <option value="">Answer like a normal message (keywords and AI)</option>
                    {ruleOptions}
                  </select>
                </div>
              ))}
              {w.questions.length < 4 && (
                <button type="button" onClick={() => setW({ ...w, questions: [...w.questions, { question: "", rule_id: null }] })}
                  className="inline-flex min-h-11 items-center gap-1.5 self-start text-[14px] font-medium text-primary"><Plus size={15} /> Add a question</button>
              )}
            </div>
          </section>

          <section>
            <h3 className="text-[14.5px] font-semibold">Chat menu</h3>
            <p className="mt-0.5 text-[13px] text-[var(--haip-fg-subtle)]">Up to 5 items, always available in the chat.</p>
            <div className="mt-3 grid gap-3">
              {w.menu.map((m, i) => (
                <div key={i} className="grid gap-2 rounded-[14px] border border-[var(--haip-border)] p-3">
                  <div className="flex gap-2">
                    <input className={field} value={m.title} maxLength={30} placeholder="Prices" onChange={e => setM(i, { title: e.target.value })} aria-label={`Menu item ${i + 1}`} />
                    <button type="button" className={iconBtn} aria-label={`Remove menu item ${i + 1}`} onClick={() => setW({ ...w, menu: w.menu.filter((_, j) => j !== i) })}><Trash2 size={15} /></button>
                  </div>
                  <select className={field} value={m.kind} onChange={e => setM(i, { kind: e.target.value as MenuItem["kind"] })} aria-label={`What menu item ${i + 1} does`}>
                    <option value="message">Send it as a message (keywords and AI answer)</option>
                    <option value="automation">Run an automation</option>
                    <option value="link">Open a link</option>
                  </select>
                  {m.kind === "automation" && (
                    <select className={field} value={m.rule_id ?? ""} onChange={e => setM(i, { rule_id: e.target.value || null })} aria-label={`Automation for menu item ${i + 1}`}>
                      <option value="">Pick an automation</option>
                      {ruleOptions}
                    </select>
                  )}
                  {m.kind === "link" && <input className={field} value={m.url ?? ""} inputMode="url" placeholder="https://…" onChange={e => setM(i, { url: e.target.value })} aria-label={`Link for menu item ${i + 1}`} />}
                </div>
              ))}
              {w.menu.length < 5 && (
                <button type="button" onClick={() => setW({ ...w, menu: [...w.menu, { title: "", kind: "message" }] })}
                  className="inline-flex min-h-11 items-center gap-1.5 self-start text-[14px] font-medium text-primary"><Plus size={15} /> Add a menu item</button>
              )}
            </div>
          </section>
        </div>
      )}
    </Drawer>
  );
}
