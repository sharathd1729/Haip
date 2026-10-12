"use client";
// One chart, four questions (leads, bookings, booked value, cash). One chart at a time keeps a single hue and a
// single scale; days before the selected period are drawn muted so the period itself reads first. Beside it, where
// the period's leads sit in the pipeline.
import { useMemo, useState } from "react";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Tabs } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { Empty, SectionTitle } from "./parts";
import { inr, inrShort, num, type BusinessOverview, type PipelineRow } from "./types";

type Measure = "leads" | "bookings" | "booking_value" | "net_collected";
const MEASURES: { value: Measure; label: string; money: boolean; unit: string }[] = [
  { value: "leads", label: "Leads", money: false, unit: "leads received" },
  { value: "bookings", label: "Bookings", money: false, unit: "bookings made" },
  { value: "booking_value", label: "Booked value", money: true, unit: "stay charge booked" },
  { value: "net_collected", label: "Cash in", money: true, unit: "collected less refunds" },
];

function day(iso: string, long = false) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", long ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" });
}

function TooltipBox({ active, payload, money, unit }: { active?: boolean; payload?: { value: number; payload: { date: string; inPeriod: boolean } }[]; money: boolean; unit: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  return (
    <div className="rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-xs shadow-md">
      <p className="font-semibold text-[var(--haip-fg)]">{day(p.payload.date, true)}</p>
      <p className="mt-0.5 tabular-nums text-[var(--haip-fg-2)]">{money ? inr(p.value) : num(p.value)} {unit}</p>
      {!p.payload.inPeriod && <p className="mt-0.5 text-[var(--haip-fg-subtle)]">before the selected period</p>}
    </div>
  );
}

export function Trends({ data }: { data: BusinessOverview }) {
  const available = MEASURES.filter(m => data.series[m.value] != null);
  const [measure, setMeasure] = useState<Measure>("leads");
  const active = available.find(m => m.value === measure) ?? available[0];
  const s = data.series;

  const rows = useMemo(() => {
    const values = (active ? s[active.value] : null) ?? [];
    return s.days.map((d, i) => ({ date: d, label: day(d), value: values[i] ?? 0, inPeriod: i >= s.period_start_index }));
  }, [s, active]);
  const inPeriod = rows.filter(r => r.inPeriod);
  const total = inPeriod.reduce((a, r) => a + r.value, 0);
  const hasData = inPeriod.some(r => r.value !== 0);
  const dense = rows.length > 14;

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <section aria-labelledby="trend-title" className="haip-card px-5 py-5 sm:px-6 lg:col-span-2">
        <SectionTitle sub={active ? `${active.unit}, per day (IST)` : undefined}
          actions={<Tabs label="Measure" value={active?.value ?? "leads"} onChange={v => setMeasure(v as Measure)} items={available.map(m => ({ value: m.value, label: m.label }))} />}>
          <span id="trend-title">Day by day</span>
        </SectionTitle>
        {!active || !hasData ? (
          <Empty>Nothing to chart for this measure in the selected period.</Empty>
        ) : (
          <>
            <p className="mb-2 text-[13px] text-[var(--haip-fg-2)]">
              <span className="font-[family-name:var(--font-display)] text-xl font-semibold tabular-nums text-[var(--haip-fg)]">{active.money ? inr(total) : num(total)}</span>{" "}
              in the period
            </p>
            <div className="h-56 sm:h-64" role="img" aria-label={`${active.label} per day. ${active.money ? inr(total) : num(total)} in the selected period.`}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} margin={{ top: 6, right: 4, left: 0, bottom: 0 }} barCategoryGap={dense ? 2 : 6}>
                  <CartesianGrid vertical={false} stroke="var(--haip-border)" />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} minTickGap={18} tick={{ fontSize: 11, fill: "var(--haip-fg-subtle)" }} />
                  <YAxis tickLine={false} axisLine={false} width={active.money ? 52 : 34} allowDecimals={false}
                    tickFormatter={v => (active.money ? inrShort(Number(v)) : String(v))} tick={{ fontSize: 11, fill: "var(--haip-fg-subtle)" }} />
                  <Tooltip cursor={{ fill: "color-mix(in srgb, var(--primary) 7%, transparent)" }} content={<TooltipBox money={active.money} unit={active.unit} />} />
                  <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={30} isAnimationActive={false}>
                    {rows.map(r => <Cell key={r.date} fill={r.inPeriod ? "var(--primary)" : "var(--haip-border-strong, #CBD5D1)"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 flex items-center gap-3 text-[11.5px] text-[var(--haip-fg-subtle)]">
              <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-primary" aria-hidden />selected period</span>
              {rows.some(r => !r.inPeriod) && <span className="inline-flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-[var(--haip-border-strong,#CBD5D1)]" aria-hidden />days before it, for context</span>}
            </p>
          </>
        )}
      </section>

      <Pipeline rows={data.pipeline} />
    </div>
  );
}

function Pipeline({ rows }: { rows: PipelineRow[] }) {
  const max = Math.max(1, ...rows.map(r => r.count));
  const total = rows.reduce((a, r) => a + r.count, 0);
  return (
    <section aria-labelledby="pipeline-title" className="haip-card px-5 py-5 sm:px-6">
      <SectionTitle sub="Leads received in this period, by the stage they are in now"><span id="pipeline-title">Pipeline</span></SectionTitle>
      {rows.length === 0 ? <Empty>No leads in this period.</Empty> : (
        <ul className="space-y-2.5">
          {rows.map(r => (
            <li key={r.stage}>
              <Link href="/dashboard/leads" className="group block rounded py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40">
                <span className="flex items-baseline justify-between gap-3 text-[13px]">
                  <span className="min-w-0 truncate text-[var(--haip-fg-2)] group-hover:text-[var(--haip-fg)]">
                    {r.stage}
                    {r.category && r.category !== "valid" && <span className="ml-1.5 text-[11px] text-[var(--haip-fg-subtle)]">not counted as a lead</span>}
                  </span>
                  <span className="font-semibold tabular-nums text-[var(--haip-fg)]">{num(r.count)}</span>
                </span>
                <span className="mt-1 block h-2 overflow-hidden rounded-sm bg-[var(--haip-surface)]" aria-hidden>
                  <span className={cn("block h-full rounded-sm motion-safe:transition-[width] motion-safe:duration-300",
                    r.won ? "bg-primary" : r.lost ? "bg-[var(--haip-fg-subtle)]/60" : r.category === "valid" ? "bg-primary/55" : "bg-[var(--haip-border-strong,#CBD5D1)]")}
                    style={{ width: `${Math.max(3, (r.count / max) * 100)}%` }} />
                </span>
              </Link>
            </li>
          ))}
          <li className="border-t border-[var(--haip-border)] pt-2 text-[12px] text-[var(--haip-fg-subtle)]">{num(total)} leads in total</li>
        </ul>
      )}
    </section>
  );
}
