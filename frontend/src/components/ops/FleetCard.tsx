"use client";
// One vehicle's fitness at a glance (GET /ops/fleet, ops_fleet_view): problems first, then papers, defects, services and the
// stock kept on board. Every rule (what is amber or red, what blocks dispatch) is the server's; this only shows it and posts.
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import type { FleetCardData, FleetLevel } from "@/lib/ops";

const TONE = { red: "danger", amber: "warning", ok: "success" } as const;

function LevelPill({ level }: { level: FleetLevel }) {
  if (!level) return null;
  return <StatusPill tone={level === "red" ? "danger" : "warning"}>{level === "red" ? "Now" : "Soon"}</StatusPill>;
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-t border-[var(--haip-border)] pt-3 first:border-t-0 first:pt-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] text-[var(--haip-fg-subtle)]">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function Line({ main, sub, right }: { main: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex min-h-[48px] items-center gap-3 py-1.5">
      <span className="min-w-0 flex-1 text-[15px]">
        {main}
        {sub && <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{sub}</span>}
      </span>
      {right && <span className="flex shrink-0 items-center gap-2">{right}</span>}
    </div>
  );
}

const small = "haip-btn-secondary min-h-11 px-3 text-[14px]";

export type FleetAction =
  | { kind: "paper" | "defect" | "service" | "stock"; propertyId: string }
  | { kind: "close_defect"; id: string; title: string }
  | { kind: "service_done"; id: string }
  | { kind: "count"; id: string; count: number }
  | { kind: "view_paper"; id: string };

export function FleetCard({ v, canWrite, canManage, busy, onAction }: {
  v: FleetCardData; canWrite: boolean; canManage: boolean; busy: boolean; onAction: (a: FleetAction) => void;
}) {
  const add = (kind: "paper" | "defect" | "service" | "stock", text: string) =>
    canWrite ? <button type="button" className={small} onClick={() => onAction({ kind, propertyId: v.property_id })}>{text}</button> : undefined;
  return (
    <Card className={cn("border-l-4", v.tone === "red" ? "border-l-[var(--haip-status-danger-fg)]" : v.tone === "amber" ? "border-l-[var(--haip-status-warning-fg)]" : "border-l-primary")}>
      <CardHeader title={v.name} tone="plain"
        description={v.km !== null ? `Odometer ${v.km.toLocaleString("en-IN")} km (last trip)` : "No odometer reading yet"}
        actions={<StatusPill tone={TONE[v.tone]}>{v.tone === "ok" ? "Fit to go" : v.tone === "red" ? "Needs you now" : "Coming up"}</StatusPill>} />
      <CardBody className="flex flex-col gap-3 px-4 pb-4">
        {v.problems.length > 0 && (
          <ul className="rounded-xl bg-[var(--haip-surface)] px-3 py-2 text-[14px]">
            {v.problems.map(p => <li key={p} className="py-0.5">{p}</li>)}
          </ul>
        )}

        <Section title="Papers" action={add("paper", "Add or renew")}>
          {v.papers.map(p => (
            <Line key={p.id} main={p.name} sub={`${p.number ? `${p.number} · ` : ""}${p.words}`}
              right={<>
                <LevelPill level={p.level} />
                {p.has_file && <button type="button" className={small} onClick={() => onAction({ kind: "view_paper", id: p.id })}>View</button>}
              </>} />
          ))}
          {v.missing_papers.length > 0 && (
            <p className="py-1 text-[13.5px] text-[var(--haip-fg-subtle)]">Not entered yet: {v.missing_papers.join(", ")}.</p>
          )}
        </Section>

        <Section title="Defects" action={add("defect", "Report")}>
          {v.defects.length === 0 ? <p className="py-1 text-[14px] text-[var(--haip-fg-subtle)]">Nothing open.</p> : v.defects.map(d => (
            <Line key={d.id} main={d.title}
              sub={`${d.severity === "critical" ? "Off sale, cannot leave" : "Fix when free"}${d.source === "photo" ? " · from a helper's photo" : ""}`}
              right={<>
                <StatusPill tone={d.severity === "critical" ? "danger" : "warning"}>{d.severity === "critical" ? "Critical" : "Minor"}</StatusPill>
                {canManage && <button type="button" className={small} disabled={busy}
                  onClick={() => onAction({ kind: "close_defect", id: d.id, title: d.title })}>Fixed</button>}
              </>} />
          ))}
        </Section>

        <Section title="Services" action={add("service", "Add")}>
          {v.services.length === 0 ? <p className="py-1 text-[14px] text-[var(--haip-fg-subtle)]">No service planned.</p> : v.services.map(s => (
            <Line key={s.id} main={s.name} sub={s.words}
              right={<>
                <LevelPill level={s.level} />
                {s.status === "open" && canWrite && <button type="button" className={small} disabled={busy}
                  onClick={() => onAction({ kind: "service_done", id: s.id })}>Done</button>}
              </>} />
          ))}
        </Section>

        <Section title="On board" action={add("stock", "Add item")}>
          {v.inventory.length === 0 ? <p className="py-1 text-[14px] text-[var(--haip-fg-subtle)]">No items listed yet.</p> : v.inventory.map(it => (
            <Line key={it.id} main={it.name}
              sub={it.count === null ? `Keep ${it.par}, not counted yet` : `${it.count} of ${it.par}${it.low ? ", restock" : ""}`}
              right={canWrite ? (
                <span className="flex items-center gap-1" aria-label={`${it.name} count`}>
                  <button type="button" className={small} disabled={busy || (it.count ?? 0) <= 0} aria-label={`One less ${it.name}`}
                    onClick={() => onAction({ kind: "count", id: it.id, count: Math.max(0, (it.count ?? 0) - 1) })}>−</button>
                  <b className={cn("w-8 text-center tabular-nums", it.low && "text-[var(--haip-status-warning-fg)]")}>{it.count ?? "–"}</b>
                  <button type="button" className={small} disabled={busy} aria-label={`One more ${it.name}`}
                    onClick={() => onAction({ kind: "count", id: it.id, count: it.count === null ? it.par : it.count + 1 })}>+</button>
                </span>
              ) : undefined} />
          ))}
        </Section>
      </CardBody>
    </Card>
  );
}
