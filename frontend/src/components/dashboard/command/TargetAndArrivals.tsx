"use client";
// Two cards side by side: this month's target on booked value (D-24: rental + add-ons of bookings made this month, IST) with a
// pace line ("where you should be today" = days elapsed / days in month), and the check-ins / check-outs from today with a
// 3 / 7 / 15 / 30-day window (a server parameter).
import Link from "next/link";
import { StatusPill } from "@/components/ui/kit";
import { Block, Hidden, Meter } from "./OwnerParts";
import { dayRange, lakh, monthName, restricted, targetBars, whenText, type Movements, type TargetBlock } from "./owner";
import type { Restricted } from "./types";

export const WINDOWS = [3, 7, 15, 30] as const;

export function TargetCard({ target }: { target: TargetBlock | Restricted }) {
  if (restricted(target)) return <Block title="Monthly target" period="booked value"><Hidden what="Targets and amounts" /></Block>;
  const title = `${monthName(target.month)} target`;
  const period = `${dayRange(target.from, target.to)} · booked value (rental + add-ons)`;
  if (!target.available) {
    return (
      <Block title={title} period={period}>
        <p className="text-[13.5px] text-[var(--haip-fg-2)]">{target.reason}</p>
        {target.booked && <p className="mt-2 text-[13px] text-[var(--haip-fg-subtle)]">Booked so far this month: <b className="tabular-nums text-[var(--haip-fg)]">{lakh(target.booked.total)}</b></p>}
        {target.href && (
          <Link href={target.href} className="mt-3 inline-flex min-h-11 items-center rounded-lg border border-[var(--haip-border)] px-3.5 text-[13px] font-semibold text-primary hover:bg-[var(--haip-surface)]">
            Set this month’s target
          </Link>
        )}
      </Block>
    );
  }
  const bars = targetBars(target);
  const pace = Math.round(target.pace_pct ?? 0);
  const ahead = (target.ahead_by ?? 0) >= 0;
  return (
    <Block title={title} period={period}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <p><span className="font-[family-name:var(--font-display)] text-[28px] font-semibold leading-none tabular-nums text-[var(--haip-fg)]">{target.achieved_pct}%</span>
              <span className="ml-1.5 text-[13px] text-[var(--haip-fg-subtle)]">of {lakh(target.target)}</span></p>
            <p className="text-[13px] tabular-nums text-[var(--haip-fg-2)]">{lakh(target.to_go)} to go · {target.days_left} day{target.days_left === 1 ? "" : "s"} left</p>
          </div>
          <Meter className="mt-3" marker={bars.pace}
            parts={[{ pct: bars.rental, tone: "primary" }, { pct: bars.addOns, tone: "soft" }]}
            label={`${target.achieved_pct}% of the target booked; the pace line is at ${pace}%`} />
          <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-[var(--haip-fg-2)]">
            <li className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-primary" aria-hidden />Rental {lakh(target.booked?.rental)}</li>
            <li className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-primary/40" aria-hidden />Add-ons {lakh(target.booked?.add_ons)}</li>
            <li className="flex items-center gap-1.5"><span className="h-3 w-0.5 bg-[var(--haip-fg)]" aria-hidden />Where you should be today ({pace}%, {lakh(target.expected_by_today)})</li>
          </ul>
          <p className="mt-2"><StatusPill tone={ahead ? "success" : "warning"}>{ahead ? `${lakh(target.ahead_by)} ahead of pace` : `${lakh(-(target.ahead_by ?? 0))} behind pace`}</StatusPill></p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Payment received</p>
          <p className="font-[family-name:var(--font-display)] text-[22px] font-semibold tabular-nums text-[var(--haip-fg)]">{lakh(target.payment_received)}</p>
          <p className="text-[11.5px] text-[var(--haip-fg-subtle)]">{dayRange(target.from, `${target.from.slice(0, 8)}${String(target.days_elapsed).padStart(2, "0")}`)} so far</p>
        </div>
      </div>
    </Block>
  );
}

export function ArrivalsCard({ movements, windowDays, onWindow, pending }: {
  movements: Movements | Restricted; windowDays: number; onWindow: (w: number) => void; pending?: boolean;
}) {
  const chips = (
    <div role="group" aria-label="How far ahead" className="flex flex-wrap gap-1.5">
      {WINDOWS.map(w => (
        <button key={w} type="button" aria-pressed={windowDays === w} onClick={() => onWindow(w)}
          className={windowDays === w
            ? "min-h-11 rounded-full border border-primary/40 bg-[var(--haip-primary-tint)] px-3 text-[12.5px] font-semibold text-primary lg:min-h-8"
            : "min-h-11 rounded-full border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[12.5px] font-semibold text-[var(--haip-fg-muted)] hover:text-[var(--haip-fg)] lg:min-h-8"}>
          Next {w} days
        </button>
      ))}
    </div>
  );
  if (restricted(movements)) return <Block title="Check-ins and check-outs" period="from today"><Hidden what="Bookings" /></Block>;
  const rows = movements.items;
  return (
    <Block title="Check-ins and check-outs" period={`from today · ${dayRange(movements.from, movements.to)} · ${movements.check_ins} in, ${movements.check_outs} out`}>
      {chips}
      <div className={pending ? "opacity-60 motion-safe:transition-opacity" : undefined}>
        {rows.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">Nothing in the next {movements.window_days} days.</p>
        ) : (
          <ul className="mt-3 divide-y divide-[var(--haip-border)]">
            {rows.slice(0, 12).map((r, i) => (
              <li key={`${r.href}-${r.kind}-${i}`}>
                <Link href={r.href} className="grid min-h-11 grid-cols-[5.5rem_auto_minmax(0,1fr)] items-center gap-x-2.5 gap-y-0.5 py-2 text-[13px] hover:bg-[var(--haip-surface)] sm:grid-cols-[6rem_auto_minmax(0,1fr)_auto]">
                  <span className="tabular-nums text-[var(--haip-fg-2)]">{whenText(r.days_from_today)}</span>
                  <StatusPill tone={r.kind === "check_in" ? "info" : "neutral"}>{r.kind === "check_in" ? "Check-in" : "Check-out"}</StatusPill>
                  <span className="min-w-0 truncate font-medium text-[var(--haip-fg)]">{r.guest}<span className="font-normal text-[var(--haip-fg-subtle)]"> · {r.property}</span></span>
                  <span className="col-span-3 truncate text-[12px] text-[var(--haip-fg-subtle)] sm:col-span-1 sm:text-right">{r.trip}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {rows.length > 12 && (
          <Link href="/dashboard/portfolio/calendar" className="mt-2 inline-flex min-h-11 items-center text-[13px] font-semibold text-primary hover:underline lg:min-h-0">
            {rows.length - 12} more on the calendar →
          </Link>
        )}
      </div>
    </Block>
  );
}
