"use client";
import { AlertCircle } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { fmt, pct, type CampaignRow, type TemplateRow } from "./analyticsTypes";

const STATUS: Record<string, string> = {
  draft: "bg-[var(--haip-surface)] text-[var(--haip-fg-muted)] border-[var(--haip-border)]", scheduled: "bg-blue-50 text-blue-700 border-blue-200",
  running: "bg-[var(--haip-primary-tint)] text-primary border-[color-mix(in_srgb,var(--primary)_25%,transparent)]", completed: "bg-green-50 text-green-700 border-green-200",
  paused: "bg-amber-50 text-amber-700 border-amber-200", deleted: "bg-[var(--haip-surface)] text-[var(--haip-fg-subtle)] border-[var(--haip-border)]",
};

// A rate with a slim meter behind it, so a column of rates can be compared at a glance.
function Rate({ value }: { value: number | null }) {
  return (
    <div className="min-w-[64px]">
      <span className="tabular-nums text-[var(--viz-ink)]">{pct(value)}</span>
      <div className="mt-1 h-1 rounded-full bg-[var(--viz-grid)] overflow-hidden" role="presentation">
        <div className="h-full rounded-full" style={{ width: `${value ?? 0}%`, background: "var(--viz-seq-2)" }} />
      </div>
    </div>
  );
}

function Failed({ count, rate }: { count: number; rate: number | null }) {
  const high = (rate ?? 0) >= 10;
  return (
    <span className={cn("tabular-nums inline-flex items-center gap-1", high ? "text-[var(--viz-fail)] font-medium" : "text-[var(--viz-ink-2)]")}>
      {high && <AlertCircle size={12} aria-label="High failure rate" />}
      {fmt(count)} <span className="text-[10px]">({pct(rate)})</span>
    </span>
  );
}

const TH = "font-medium px-3 py-2 text-left whitespace-nowrap";

export function CampaignTable({ rows, onOpen }: { rows: CampaignRow[]; onOpen: (c: CampaignRow) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[var(--viz-ink-2)] border-b border-[var(--haip-border)]">
          <tr>
            <th className={TH}>Campaign</th><th className={TH}>Template</th><th className={cn(TH, "text-right")}>Sent</th>
            <th className={TH}>Delivered</th><th className={TH}>Read</th><th className={TH}>Failed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--haip-border)]">
          {rows.map(c => (
            <tr key={c.id} className="hover:bg-[var(--haip-surface)]">
              <td className="px-3 py-2.5">
                <button type="button" onClick={() => onOpen(c)} className="font-semibold text-[var(--viz-ink)] hover:text-primary text-left">{c.name}</button>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded-full border capitalize", STATUS[c.status] ?? STATUS.draft)}>{c.status}</span>
                  {c.created_at && <span className="text-[10px] text-[var(--viz-ink-3)]">{new Date(c.created_at).toLocaleDateString([], { day: "numeric", month: "short" })}</span>}
                </div>
              </td>
              <td className="px-3 py-2.5 font-mono text-[11px] text-[var(--viz-ink-2)]">{c.template_name ?? "—"}</td>
              <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-[var(--viz-ink)]">{fmt(c.sent)}</td>
              <td className="px-3 py-2.5"><Rate value={c.delivery_rate} /></td>
              <td className="px-3 py-2.5"><Rate value={c.read_rate} /></td>
              <td className="px-3 py-2.5"><Failed count={c.failed} rate={c.failure_rate} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TemplateTable({ rows }: { rows: TemplateRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[var(--viz-ink-2)] border-b border-[var(--haip-border)]">
          <tr>
            <th className={TH}>Template</th><th className={cn(TH, "text-right")}>Campaigns</th><th className={cn(TH, "text-right")}>Sent</th>
            <th className={TH}>Delivered</th><th className={TH}>Read</th><th className={TH}>Failed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--haip-border)]">
          {rows.map(t => (
            <tr key={t.template_name} className="hover:bg-[var(--haip-surface)]">
              <td className="px-3 py-2.5 font-mono text-[11px] font-semibold text-[var(--viz-ink)]">{t.template_name}</td>
              <td className="px-3 py-2.5 text-right tabular-nums text-[var(--viz-ink-2)]">{t.campaigns}</td>
              <td className="px-3 py-2.5 text-right tabular-nums font-semibold text-[var(--viz-ink)]">{fmt(t.sent)}</td>
              <td className="px-3 py-2.5"><Rate value={t.delivery_rate} /></td>
              <td className="px-3 py-2.5"><Rate value={t.read_rate} /></td>
              <td className="px-3 py-2.5"><Failed count={t.failed} rate={t.failure_rate} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
