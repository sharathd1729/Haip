"use client";
// Six health checks as colour pills (the word carries the meaning); tapping one opens its evidence: the numbers against their
// thresholds, record ids and up to three anonymised guest quotes (first name, numbers masked by the backend).
import { useState } from "react";
import { Card, CardBody, CardHeader, Drawer, StatusPill } from "@/components/ui/kit";
import { Shield } from "@/lib/icons";
import { STATUS_LABEL, STATUS_TONE, type HealthCheck } from "./types";

function fmt(metric: string, v: number | null): string {
  if (v === null || v === undefined) return "No data";
  if (metric.endsWith("_share") || metric === "dm_to_lead") return `${Math.round(v * 100)}%`;
  if (metric.endsWith("_minutes")) return `${Math.round(v)} min`;
  return `${v}`;
}

export function HealthChecks({ checks, periodLabel }: { checks: HealthCheck[]; periodLabel: string }) {
  const [open, setOpen] = useState<HealthCheck | null>(null);
  return (
    <Card>
      <CardHeader icon={Shield} title="Health checks" description={periodLabel} />
      <CardBody>
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {checks.map(c => (
            <li key={c.key}>
              <button type="button" onClick={() => setOpen(c)}
                className="flex min-h-[44px] w-full items-center justify-between gap-3 rounded-xl border border-[var(--haip-border)] px-3 py-2 text-left hover:bg-[var(--haip-surface)]">
                <span className="text-sm font-semibold text-[var(--haip-fg)]">{c.label}</span>
                <StatusPill tone={STATUS_TONE[c.status]}>{STATUS_LABEL[c.status]}</StatusPill>
              </button>
            </li>
          ))}
        </ul>
      </CardBody>
      <Drawer open={open !== null} onOpenChange={o => !o && setOpen(null)} title={open?.label ?? ""}
        description={open ? `${STATUS_LABEL[open.status]} · ${periodLabel}` : undefined}>
        {open && (
          <div className="space-y-4">
            {(open.metrics ?? []).map(m => (
              <div key={m.metric} className="rounded-xl border border-[var(--haip-border)] p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-[var(--haip-fg)]">{fmt(m.metric, m.value)}</span>
                  <StatusPill tone={STATUS_TONE[m.status]}>{STATUS_LABEL[m.status]}</StatusPill>
                </div>
                <p className="mt-1 text-xs text-[var(--haip-fg-muted)]">{m.explain}</p>
                <p className="mt-1 text-[11px] text-[var(--haip-fg-subtle)]">
                  Watch at {fmt(m.metric, m.amber_at)}, act at {fmt(m.metric, m.red_at)} ({m.worse_when === "above" ? "higher is worse" : "lower is worse"});
                  judged from {m.min_base} cases (this period: {m.base}).
                </p>
              </div>
            ))}
            {(open.evidence?.quotes ?? []).length > 0 && (
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">What guests said</p>
                <ul className="space-y-2">
                  {open.evidence!.quotes.map((q, i) => (
                    <li key={i} className="rounded-xl bg-[var(--haip-surface)] p-3 text-sm text-[var(--haip-fg)]">
                      <span className="font-semibold">{q.who}:</span> “{q.text}”
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {Object.entries(open.evidence?.ids ?? {}).filter(([, v]) => v.length > 0).map(([k, v]) => (
              <p key={k} className="text-xs text-[var(--haip-fg-subtle)]">{k.replace(/_/g, " ")}: {v.length} record{v.length === 1 ? "" : "s"}</p>
            ))}
          </div>
        )}
      </Drawer>
    </Card>
  );
}
