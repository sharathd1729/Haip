"use client";
// Ops Today building blocks (direction A "Needs you", unit cards on top for <= 6 units; owner pick 25 Oct 2026).
// Big tap targets, plain words, problems only. Colours come from the status tokens; the words carry the meaning.
import Link from "next/link";
import { cn } from "@/lib/utils";
import { StatusPill } from "@/components/ui/kit";
import { whenLabel, type OpsDayEntry, type OpsNeed, type OpsUnit, type UnitTone } from "@/lib/ops";

const TONE_PILL = { red: "danger", amber: "warning", ok: "success", idle: "neutral" } as const;
const TONE_EDGE: Record<UnitTone, string> = {
  red: "border-l-[var(--haip-status-danger-fg)]",
  amber: "border-l-[var(--haip-status-warning-fg)]",
  ok: "border-l-primary",
  idle: "border-l-[var(--haip-border-strong)]",
};
const DOT: Record<UnitTone, string> = {
  red: "bg-[var(--haip-status-danger-fg)]", amber: "bg-[var(--haip-status-warning-fg)]",
  ok: "bg-primary", idle: "bg-[var(--haip-border-strong)]",
};

/** Readiness as ten segments (no inline width): how many of the checklist items are green. */
export function ReadyBar({ pct, label }: { pct: number; label: string }) {
  const on = Math.round(pct / 10);
  return (
    <span role="img" aria-label={label} className="mt-2 flex gap-[3px]">
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} className={cn("h-1.5 flex-1 rounded-full", i < on ? "bg-primary" : "bg-[var(--haip-border)]")} />
      ))}
    </span>
  );
}

export function UnitCards({ units }: { units: OpsUnit[] }) {
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
      {units.map(u => {
        const body = (
          <>
            <span className="flex items-center gap-2">
              <span aria-hidden className={cn("size-2.5 shrink-0 rounded-full", DOT[u.tone])} />
              <span className="truncate font-[family-name:var(--font-display)] text-[16px] font-semibold">{u.name}</span>
            </span>
            <span className="mt-0.5 block text-[13px] font-semibold text-[var(--haip-fg-muted)]">{u.status}</span>
            {u.problem && <span className="mt-1 block text-[12.5px] leading-snug text-[var(--haip-status-danger-fg)]">{u.problem}</span>}
            {u.ready_pct !== null && <ReadyBar pct={u.ready_pct} label={`${u.ready_pct}% of checks green`} />}
          </>
        );
        const cls = cn("haip-card block min-h-[88px] min-w-0 border-l-4 p-3 text-left", TONE_EDGE[u.tone]);
        return u.file_id
          ? <Link key={u.property_id} href={`/dashboard/ops/files/${u.file_id}`} className={cn(cls, "transition-transform active:scale-[0.98]")}>{body}</Link>
          : <div key={u.property_id} className={cls}>{body}</div>;
      })}
    </div>
  );
}

export function NeedCard({ need, onResolve, resolving }: { need: OpsNeed; onResolve?: (id: string) => void; resolving?: boolean }) {
  const red = need.level === "red";
  return (
    <article className={cn("rounded-2xl border p-4",
      red ? "border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)]"
          : "border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)]")}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill tone={red ? "danger" : "warning"}>{red ? "Needs you now" : "Today"}</StatusPill>
        <span className="text-[13px] font-semibold text-[var(--haip-fg-muted)]">{need.unit}</span>
      </div>
      <h3 className="mt-2 text-[17px] font-semibold leading-snug text-[var(--haip-fg)]">{need.title}</h3>
      {need.detail && <p className="mt-1 text-[14.5px] leading-snug text-[var(--haip-fg-muted)]">{need.detail}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {need.file_id && (
          <Link href={`/dashboard/ops/files/${need.file_id}`} className="haip-btn-primary min-h-12 flex-1 text-[15px]">
            Open trip
          </Link>
        )}
        {need.action === "resolve_item" && need.item_id && onResolve && (
          <button type="button" disabled={resolving} onClick={() => onResolve(need.item_id!)}
            className={cn("min-h-12 flex-1 text-[15px]", need.file_id ? "haip-btn-secondary" : "haip-btn-primary")}>
            {resolving ? "Saving…" : "Mark as sorted"}
          </button>
        )}
      </div>
    </article>
  );
}

export function DayList({ day, today }: { day: OpsDayEntry[]; today: string }) {
  return (
    <ul className="haip-card divide-y divide-[var(--haip-border)] px-4">
      {day.map((e, i) => (
        <li key={`${e.file_id}-${i}`}>
          <Link href={`/dashboard/ops/files/${e.file_id}`} className="grid min-h-[56px] grid-cols-[84px_1fr_auto] items-center gap-3 py-2.5">
            <span className="text-[13px] tabular-nums text-[var(--haip-fg-subtle)]">{whenLabel(e, today)}</span>
            <span className="min-w-0">
              <span className="block truncate text-[15px] text-[var(--haip-fg)]">{e.what}</span>
              <span className="block truncate text-[13px] text-[var(--haip-fg-subtle)]">{e.sub}</span>
            </span>
            <StatusPill tone={TONE_PILL[e.tone]} className="sr-only sm:not-sr-only">
              {e.tone === "red" ? "Problem" : e.tone === "amber" ? "Getting ready" : e.tone === "ok" ? "On track" : "Later"}
            </StatusPill>
          </Link>
        </li>
      ))}
    </ul>
  );
}
