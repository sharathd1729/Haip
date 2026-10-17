"use client";
// Today strip (Hospitality Hybrid Home): what is happening on the ground today, before any period numbers. Who starts and
// ends a stay today, where each vehicle or room is right now, and how many people are waiting on the team. Reads the same
// GET /calendar the Calendar page uses (no amounts are shown, so it needs no revenue rights) and the shared work queue.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { canSeeNav } from "@/lib/permissions";
import { ArrowRight, Zap } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { useBusinessType } from "@/components/providers/WorkspaceProvider";
import { useNav } from "@/components/layout/nav";

interface Stay { id: string; check_in: string; check_out: string; status: string; guest_name: string; adults: number }
interface Block { id: string; blocked_from: string; blocked_to: string; reason: string; event?: { title: string } | null }
interface Row { property_id: string; property_name: string; stays: Stay[]; blocks: Block[] }
interface CalendarDay { properties: Row[] }

const IST = "Asia/Kolkata";
/** YYYY-MM-DD for a day in India time, offset by `plus` days. */
export function istDay(plus = 0): string {
  const d = new Date(Date.now() + plus * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}
function weekday(iso: string): string {
  return new Date(`${iso}T12:00:00+05:30`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: IST });
}
const live = (s: Stay) => s.status !== "cancelled";
const firstName = (n: string) => n.trim().split(/\s+/)[0] || n;

export type UnitState =
  | { kind: "starts"; guest: string; until: string }
  | { kind: "out"; guest: string; until: string }
  | { kind: "back"; guest: string }
  | { kind: "blocked"; why: string }
  | { kind: "free" };

/** Where one vehicle or room is today. A stay that starts today wins over one that ends today (a same-day turnaround). */
export function unitState(row: Row, today: string): UnitState {
  const stays = row.stays.filter(live);
  const starts = stays.find(s => s.check_in === today);
  if (starts) return { kind: "starts", guest: starts.guest_name, until: starts.check_out };
  const out = stays.find(s => s.check_in < today && today < s.check_out);
  if (out) return { kind: "out", guest: out.guest_name, until: out.check_out };
  const back = stays.find(s => s.check_out === today);
  if (back) return { kind: "back", guest: back.guest_name };
  const block = row.blocks.find(b => b.blocked_from <= today && today < b.blocked_to);
  if (block) return { kind: "blocked", why: block.event?.title || (block.reason === "maintenance" ? "Maintenance" : "Blocked") };
  return { kind: "free" };
}

const DOT: Record<UnitState["kind"], string> = {
  starts: "bg-[var(--haip-accent)]", out: "bg-primary", back: "bg-[var(--haip-status-success-fg)]",
  blocked: "bg-[var(--haip-status-neutral-fg)]", free: "bg-[var(--haip-border-strong)]",
};

function stateText(s: UnitState): { line: string; sub?: string } {
  switch (s.kind) {
    case "starts": return { line: `Leaves today with ${firstName(s.guest)}`, sub: `back ${weekday(s.until)}` };
    case "out": return { line: `Out with ${firstName(s.guest)}`, sub: `back ${weekday(s.until)}` };
    case "back": return { line: `Back today from ${firstName(s.guest)}` };
    case "blocked": return { line: s.why };
    case "free": return { line: "Free today" };
  }
}

export function TodayStrip({ role }: { role: string }) {
  const businessType = useBusinessType();
  const caravan = businessType === "caravan";
  const canSeeCalendar = canSeeNav(role, "properties");
  const nav = useNav(role);
  const today = istDay(0);
  const tomorrow = istDay(1);
  const { data, isLoading, isError } = useQuery<CalendarDay>({
    queryKey: ["portfolio-calendar", today, tomorrow],
    queryFn: () => api.get(`/calendar?from_date=${today}&to_date=${tomorrow}`).then(r => r.data),
    enabled: canSeeCalendar,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  // The "Unassigned" overflow row only matters while it holds a real booking.
  const rows = (data?.properties ?? []).filter(r => !/^unassigned$/i.test(r.property_name.trim()) || r.stays.some(live));
  const stays = rows.flatMap(r => r.stays.filter(live).map(s => ({ ...s, unit: r.property_name })));
  const starting = stays.filter(s => s.check_in === today);
  const ending = stays.filter(s => s.check_out === today);
  const unitWord = caravan ? "vehicle" : "unit";

  return (
    <section aria-labelledby="today-title" className="haip-card overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-4 pt-4 sm:px-5">
        <h2 id="today-title" className="font-[family-name:var(--font-display)] text-[17px] font-semibold tracking-[-0.01em] text-[var(--haip-fg)]">
          Today <span className="text-[14px] font-medium text-[var(--haip-fg-subtle)]">{weekday(today)}</span>
        </h2>
        {canSeeCalendar && <Link href="/dashboard/portfolio/calendar" className="inline-flex min-h-11 items-center gap-1 text-[13.5px] font-semibold text-primary hover:underline sm:min-h-0">Calendar<ArrowRight size={14} /></Link>}
      </div>

      <div className={cn("mt-3 grid gap-px border-t border-[var(--haip-border)] bg-[var(--haip-border)] [&>*]:bg-[var(--haip-card)]", canSeeCalendar ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.7fr)]" : "grid-cols-1")}>
        <Link href="/dashboard/my-day" className={cn("group flex min-h-[92px] flex-col justify-between gap-1 px-4 py-3 transition-colors hover:bg-[var(--hover-bg)] sm:px-5", canSeeCalendar && "col-span-2 sm:col-span-1")}>
          <span className="text-[13px] font-medium text-[var(--haip-fg-muted)]">Waiting on the team</span>
          <span className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground"><Zap size={16} /></span>
            <span className="num font-[family-name:var(--font-display)] text-[28px] font-semibold leading-none text-[var(--haip-fg)]">{nav.waiting}</span>
          </span>
          <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">{nav.waiting === 1 ? "person" : "people"} · open My day</span>
        </Link>
        <Movement label={caravan ? "Trips starting" : "Check-ins"} people={starting.map(s => `${firstName(s.guest_name)} · ${s.unit}`)} loading={canSeeCalendar && isLoading} hidden={!canSeeCalendar} />
        <Movement label={caravan ? "Coming back" : "Check-outs"} people={ending.map(s => `${firstName(s.guest_name)} · ${s.unit}`)} loading={canSeeCalendar && isLoading} hidden={!canSeeCalendar} />

        {canSeeCalendar && (
          <div className="col-span-2 px-4 py-3 sm:col-span-3 sm:px-5 lg:col-span-1">
            <span className="text-[13px] font-medium text-[var(--haip-fg-muted)]">{caravan ? "Vehicles" : "Units"} right now</span>
            {isLoading ? (
              <div className="mt-2 space-y-2"><Skeleton className="h-5 w-full" /><Skeleton className="h-5 w-3/4" /></div>
            ) : isError ? (
              <p className="mt-2 text-[13px] text-[var(--haip-status-danger-fg)]">Couldn’t load the calendar.</p>
            ) : rows.length === 0 ? (
              <p className="mt-2 text-[13px] text-[var(--haip-fg-subtle)]">No {unitWord}s set up yet.</p>
            ) : (
              <ul className="mt-1.5 space-y-1.5">
                {rows.slice(0, 4).map(r => {
                  const st = unitState(r, today);
                  const t = stateText(st);
                  return (
                    <li key={r.property_id} className="flex min-w-0 items-center gap-2 text-[13.5px]">
                      <span className={cn("size-2.5 shrink-0 rounded-full", DOT[st.kind])} aria-hidden />
                      <span className="shrink-0 font-semibold text-[var(--haip-fg)]">{r.property_name}</span>
                      <span className="min-w-0 truncate text-[var(--haip-fg-2)]">{t.line}{t.sub && <span className="text-[var(--haip-fg-subtle)]"> · {t.sub}</span>}</span>
                    </li>
                  );
                })}
                {rows.length > 4 && <li className="text-[12.5px] text-[var(--haip-fg-subtle)]">+{rows.length - 4} more on the calendar</li>}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function Movement({ label, people, loading, hidden }: { label: string; people: string[]; loading: boolean; hidden: boolean }) {
  if (hidden) return null;
  return (
    <div className="flex min-h-[92px] min-w-0 flex-col justify-between gap-1 px-4 py-3 sm:px-5">
      <span className="text-[13px] font-medium text-[var(--haip-fg-muted)]">{label}</span>
      {loading ? <Skeleton className="h-7 w-10" /> : (
        <span className={cn("num font-[family-name:var(--font-display)] text-[28px] font-semibold leading-none", people.length ? "text-[var(--haip-fg)]" : "text-[var(--haip-fg-subtle)]")}>{people.length}</span>
      )}
      <span className="truncate text-[12.5px] text-[var(--haip-fg-subtle)]" title={people.join(", ")}>{loading ? " " : people.length ? people.join(", ") : "none today"}</span>
    </div>
  );
}
