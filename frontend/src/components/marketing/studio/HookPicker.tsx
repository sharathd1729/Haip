"use client";
// Reel opening lines (Instagram toolkit phase 2): three options from the hook library, scored by code. Under 50 they
// stay visible but greyed with the reason; one that breaks the price policy is blocked. "Use this" puts the on-screen
// line on the first clip as a new version and saves the formula. Below: the spoken script as a timed shot list.
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { StatusPill } from "@/components/ui/kit";
import { STUDIO, btn, studioError, type ContentItem, type HookPlan } from "./types";

const clock = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(0).padStart(2, "0")}`;

export function HookPicker({ itemId, versionId, plan, formula, canChoose, onChanged }: {
  itemId: string; versionId: string; plan: HookPlan; formula: string | null; canChoose: boolean; onChanged: (d: ContentItem) => void;
}) {
  const { toast } = useToast();
  const choose = useMutation({
    mutationFn: (n: number) => api.post(`${STUDIO}/content/${itemId}/hooks/${n}/choose`, { version_id: versionId }).then(r => r.data as ContentItem),
    onSuccess: d => { onChanged(d); toast({ variant: "success", title: "Opening line set", description: "Saved on the first clip as a new version." }); },
    onError: e => toast({ variant: "error", title: "Not set", description: studioError(e, "Try again.") }),
  });

  if (plan.status === "failed") {
    return <p className="rounded-lg bg-[var(--haip-status-warning-bg)] p-3 text-sm text-[var(--haip-status-warning-fg)]">{plan.error ?? "No hook options this time."}</p>;
  }
  const options = plan.options ?? [];
  const sheet = plan.beats;
  return (
    <section className="space-y-3" aria-label="Opening line">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold text-[var(--haip-fg)]">Pick an opening line</h3>
        {formula && <span className="text-xs text-[var(--haip-fg-subtle)]">Using: {formula}</span>}
      </div>
      <ul className="space-y-2">
        {options.map((o, i) => {
          const dim = o.blocked || o.score < 50;
          const chosen = plan.chosen === i;
          return (
            <li key={i} className={`rounded-xl border p-3 ${chosen ? "border-primary bg-[var(--haip-status-success-bg)]" : "border-[var(--haip-border)]"} ${dim ? "opacity-60" : ""}`}>
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-sm font-semibold text-[var(--haip-fg)]">“{o.spoken}”</p>
                  <p className="text-xs text-[var(--haip-fg-subtle)]">{o.formula} · on screen: {o.on_screen}</p>
                  {o.reason && <p className="text-xs text-[var(--haip-fg-2)]">{o.blocked ? "Blocked: " : ""}{o.reason}</p>}
                </div>
                <span className={`font-mono text-base font-semibold tabular-nums ${o.blocked || o.score < 50 ? "text-[var(--haip-status-danger-fg)]" : o.score >= 70 ? "text-[var(--haip-status-success-fg)]" : "text-[var(--haip-fg-2)]"}`}
                  aria-label={`Hook score ${o.score} out of 100`}>{o.score}</span>
              </div>
              {canChoose && !o.blocked && !chosen && (
                <button type="button" className={`${btn} mt-2`} disabled={choose.isPending} onClick={() => choose.mutate(i)}>Use this</button>
              )}
              {chosen && <StatusPill tone="success" className="mt-2">In use</StatusPill>}
            </li>
          );
        })}
      </ul>
      <p className="text-xs text-[var(--haip-fg-subtle)]">The score catches weak openings (greetings, nothing concrete, too long). It can't predict views.</p>

      {sheet && sheet.rows.length > 0 && (
        <div className="space-y-2">
          <p className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Script and shot list · about {Math.round(sheet.total_seconds)} seconds</p>
          <ol className="divide-y divide-dashed divide-[var(--haip-border)]">
            {sheet.rows.map(r => (
              <li key={r.n} className="grid grid-cols-[4.5rem_1fr] gap-2 py-2 text-sm">
                <span className="font-mono text-xs text-[var(--haip-fg-subtle)]">{clock(r.start)}–{clock(r.start + r.seconds)}</span>
                <span className="min-w-0">
                  <span className="text-[var(--haip-fg)]">{r.label && <b className="mr-1">{r.label}:</b>}{r.line}</span>
                  <span className="block text-xs text-[var(--haip-fg-subtle)]">{r.shot}</span>
                  {r.flags.map(f => <StatusPill key={f} tone="warning" className="mr-1 mt-1">{f}</StatusPill>)}
                </span>
              </li>
            ))}
          </ol>
          {sheet.notes.length > 0 && <ul className="list-disc space-y-1 pl-5 text-xs text-[var(--haip-fg-subtle)]">{sheet.notes.map(n => <li key={n}>{n}</li>)}</ul>}
        </div>
      )}
    </section>
  );
}
