"use client";
// Bookings value vs cash collected per IST month, with the go-live month marked. One axis (rupees), two series with a legend,
// thin bars with rounded tops, a tooltip per month (hover or focus) and a table view of the same numbers.
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cn } from "@/lib/utils";
import { Tabs } from "@/components/ui/kit";
import { inr, inrShort, num } from "@/components/dashboard/command/types";
import { formatDay, formatMonth, type RevenueMonth } from "./types";

const SERIES = [
  { key: "booked_value" as const, label: "Bookings value", swatch: "bg-[var(--haip-series-1)]", color: "var(--haip-series-1)" },
  { key: "collected" as const, label: "Cash collected", swatch: "bg-[var(--haip-series-2)]", color: "var(--haip-series-2)" },
];

type Row = RevenueMonth & { label: string };

function TooltipBox({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null;
  const m = payload[0].payload;
  return (
    <div className="rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-xs shadow-md">
      <p className="font-semibold text-[var(--haip-fg)]">{formatMonth(m.month)}</p>
      <p className="text-[var(--haip-fg-subtle)]">{formatDay(m.from)} – {formatDay(m.to)}</p>
      {SERIES.map(s => (
        <p key={s.key} className="mt-0.5 flex items-center justify-between gap-3 text-[var(--haip-fg-2)]">
          <span className="flex items-center gap-1.5"><span className={cn("size-2 rounded-sm", s.swatch)} />{s.label}</span>
          <span className="tabular-nums text-[var(--haip-fg)]">{inr(m[s.key])}</span>
        </p>
      ))}
    </div>
  );
}

export function RevenueChart({ months, goLiveMonth }: { months: RevenueMonth[]; goLiveMonth: string }) {
  const [view, setView] = useState("chart");
  const rows: Row[] = useMemo(() => months.map(m => ({ ...m, label: formatMonth(m.month).slice(0, 3) + " " + m.month.slice(2, 4) })), [months]);
  const goLive = rows.find(r => r.month === goLiveMonth);
  const empty = months.every(m => !m.booked_value && !m.collected);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-[var(--haip-fg-muted)]" aria-label="Legend">
          {SERIES.map(s => <li key={s.key} className="flex items-center gap-1.5"><span className={cn("size-2.5 rounded-sm", s.swatch)} />{s.label}</li>)}
          <li className="flex items-center gap-1.5"><span className="h-3 border-l-2 border-dashed border-[var(--haip-fg-subtle)]" />Go-live month</li>
        </ul>
        <Tabs label="Revenue view" value={view} onChange={setView} items={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]} />
      </div>

      {view === "table" || empty ? (
        <>
          {empty && <p className="mt-3 text-[13px] text-[var(--haip-fg-subtle)]">No bookings or payments in these months yet.</p>}
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-[13px] sm:text-[13.5px]">
              <thead><tr className="text-left text-[12px] text-[var(--haip-fg-subtle)]">
                <th className="py-2 font-semibold">Month (IST)</th><th className="py-2 text-right font-semibold">Bookings made</th>
                <th className="py-2 text-right font-semibold">Bookings value</th><th className="py-2 text-right font-semibold">Cash collected</th>
              </tr></thead>
              <tbody>
                {months.map(m => (
                  <tr key={m.month} className="border-t border-[var(--haip-border)]">
                    <td className="py-2">{formatMonth(m.month)}{m.month === goLiveMonth && <span className="ml-1.5 text-[12px] text-[var(--haip-fg-subtle)]">go-live</span>}</td>
                    <td className="py-2 text-right tabular-nums">{num(m.bookings)}</td>
                    <td className="py-2 text-right tabular-nums">{inr(m.booked_value)}</td>
                    <td className="py-2 text-right tabular-nums">{inr(m.collected)}{m.refunded > 0 && <span className="block text-[11.5px] text-[var(--haip-fg-subtle)]">refunds {inr(m.refunded)}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="mt-4 h-56 sm:h-64" role="img" aria-label="Bookings value and cash collected per month. The table view lists every number.">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <BarChart data={rows} margin={{ top: 16, right: 4, left: 0, bottom: 0 }} barCategoryGap="22%" barGap={2}>
              <CartesianGrid vertical={false} stroke="var(--haip-border)" />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "var(--haip-fg-subtle)" }} />
              <YAxis tickLine={false} axisLine={false} width={52} tickFormatter={v => inrShort(Number(v))} tick={{ fontSize: 11, fill: "var(--haip-fg-subtle)" }} />
              <Tooltip cursor={{ fill: "color-mix(in srgb, var(--primary) 7%, transparent)" }} content={<TooltipBox />} />
              {goLive && <ReferenceLine x={goLive.label} stroke="var(--haip-fg-subtle)" strokeDasharray="4 3"
                label={{ value: "Go-live", position: "top", fontSize: 11, fill: "var(--haip-fg-subtle)" }} />}
              {SERIES.map(s => <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[4, 4, 0, 0]} maxBarSize={18} isAnimationActive={false} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
