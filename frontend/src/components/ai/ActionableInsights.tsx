"use client";
// The actionable read of a lead or a call (backend services/ai_actionable.py): ONE next best action with owner,
// channel and deadline, the blocking objection + a suggested counter, lead temperature, missed revenue (₹ only when
// the figure was actually said) and what to update in HAIP. Renders nothing when the analysis has none of it
// (older analyses, or the model gave nothing usable).
import { ArrowRight, AlertTriangle, IndianRupee, Flame, Edit2 } from "@/lib/icons";
import { StatusPill } from "@/components/ui/page";
import { channelLabel, formatInr, groundedMissedTotal, hasActionable, temperatureTone, type Actionable } from "@/lib/actionable";

export function ActionableInsights({ insights, compact = false }: { insights?: Actionable | null; compact?: boolean }) {
  if (!insights || !hasActionable(insights)) return null;
  const nba = insights.next_best_action;
  const objection = insights.blocking_objection;
  const temp = insights.temperature;
  const missed = insights.missed_revenue ?? [];
  const updates = insights.haip_updates ?? [];
  const missedTotal = groundedMissedTotal(missed);
  const meta = nba ? [nba.owner, channelLabel(nba.channel), nba.deadline].filter(Boolean) : [];

  return (
    <div className="space-y-2.5">
      {nba?.action && (
        <div className="rounded-xl border border-[color-mix(in_srgb,var(--primary)_22%,transparent)] bg-[var(--haip-primary-tint)] p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">Next best action</p>
          <p className="mt-1 flex items-start gap-1.5 text-[13px] font-semibold leading-snug text-[var(--haip-fg)]">
            <ArrowRight size={14} className="mt-0.5 flex-shrink-0 text-primary" />
            <span>{nba.action}</span>
          </p>
          {meta.length > 0 && <p className="mt-1 text-[12px] text-[var(--haip-fg-muted)]">{meta.join(" · ")}</p>}
          {!compact && nba.why && <p className="mt-1 text-[12px] text-[var(--haip-fg-subtle)]">{nba.why}</p>}
        </div>
      )}

      {(temp || objection) && (
        <div className="flex flex-wrap items-start gap-2">
          {temp && (
            <StatusPill tone={temperatureTone(temp.value)}>
              <Flame size={12} /> <span className="capitalize">{temp.value}</span>
            </StatusPill>
          )}
          {temp?.reason && <span className="min-w-0 flex-1 text-[12px] text-[var(--haip-fg-muted)]">{temp.reason}</span>}
        </div>
      )}

      {objection && (
        <div className="rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] p-3">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--haip-status-warning-fg)]">
            <AlertTriangle size={13} /> Blocking: {objection.objection}
          </p>
          {objection.counter && <p className="mt-1 text-[12px] text-[var(--haip-fg)]">Try: {objection.counter}</p>}
        </div>
      )}

      {!compact && missed.length > 0 && (
        <div className="rounded-xl border border-[var(--haip-border)] p-3">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--haip-fg)]">
            <IndianRupee size={13} /> Missed revenue{missedTotal > 0 ? ` · ${formatInr(missedTotal)} stated` : ""}
          </p>
          <ul className="mt-1.5 space-y-1">
            {missed.map((m, i) => (
              <li key={i} className="text-[12px] text-[var(--haip-fg-muted)]">
                {m.what}
                {m.grounded && m.est_inr ? <span className="font-semibold text-[var(--haip-fg)]"> · {formatInr(m.est_inr)}</span> : null}
                {m.evidence && <span className="block italic text-[var(--haip-fg-subtle)]">&ldquo;{m.evidence}&rdquo;</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {!compact && updates.length > 0 && (
        <div className="rounded-xl border border-[var(--haip-border)] p-3">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold text-[var(--haip-fg)]">
            <Edit2 size={13} /> Update in HAIP
          </p>
          <ul className="mt-1.5 space-y-1">
            {updates.map((u, i) => (
              <li key={i} className="text-[12px] text-[var(--haip-fg-muted)]">
                <span className="font-medium text-[var(--haip-fg)]">{u.field.replace(/_/g, " ")}</span> → {u.value}
                {u.why ? <span className="text-[var(--haip-fg-subtle)]"> ({u.why})</span> : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
