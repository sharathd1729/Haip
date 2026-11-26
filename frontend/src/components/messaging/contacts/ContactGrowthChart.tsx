"use client";
// New contacts and opt-outs per day, last 30 days, one count axis. Data: GET /messaging/subscribers/growth.
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import api from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartCard } from "@/components/messaging/analytics/AnalyticsCharts";
import { netGrowth, periodLabel, plural, type GrowthDay } from "./contactsHelpers";

interface Growth { from: string; to: string; daily: GrowthDay[]; new_total: number; opted_out_total: number }

const AXIS = { fontSize: 11, fill: "var(--viz-ink-3)" } as const;
const short = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

function Key({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className={`inline-block h-2.5 w-2.5 rounded-[3px] ${swatch}`} />
      {label}
    </span>
  );
}

export function ContactGrowthChart() {
  const { data, isLoading, isError, refetch } = useQuery<Growth>({
    queryKey: ["wa-subscriber-growth"],
    queryFn: () => api.get("/messaging/subscribers/growth").then(r => r.data),
    staleTime: 60_000,
  });

  if (isLoading) return <Skeleton className="h-44 rounded-2xl" />;
  if (isError || !data) {
    return (
      <p className="text-xs text-[var(--haip-fg-subtle)] rounded-2xl border border-[var(--haip-border)] px-4 py-3">
        Couldn&apos;t load contact growth. <button type="button" onClick={() => refetch()} className="text-primary font-semibold underline">Try again</button>
      </p>
    );
  }

  const net = netGrowth(data.daily);
  const empty = data.new_total === 0 && data.opted_out_total === 0;
  return (
    <ChartCard
      title="Contact growth, last 30 days"
      subtitle={`${periodLabel(data.from, data.to)} · ${plural(data.new_total, "new contact")}, ${plural(data.opted_out_total, "opt-out")} · net ${net >= 0 ? "+" : ""}${net.toLocaleString("en-IN")}`}
      legend={<><Key swatch="bg-[var(--viz-1)]" label="New contacts" /><Key swatch="bg-[var(--viz-2)]" label="Opted out" /></>}
      table={{ columns: ["Day", "New", "Opted out"], rows: data.daily.map(d => [short(d.date), d.new, d.opted_out]) }}
    >
      {empty ? (
        <p className="text-xs text-[var(--viz-ink-2)] py-6 text-center">No new contacts or opt-outs in the last 30 days.</p>
      ) : (
        <div className="h-36" role="img" aria-label="Column chart of new contacts and opt-outs per day, last 30 days">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.daily} margin={{ top: 4, right: 4, bottom: 0, left: -20 }} barGap={1}>
              <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
              <XAxis dataKey="date" tickFormatter={short} tick={AXIS} axisLine={false} tickLine={false} minTickGap={32} />
              <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip cursor={{ fill: "var(--viz-grid)" }} content={({ active, payload }) => {
                const d = active && (payload?.[0]?.payload as GrowthDay | undefined);
                if (!d) return null;
                return (
                  <div className="rounded-lg border border-[var(--haip-border)] bg-[var(--viz-surface)] px-3 py-2 shadow-md text-xs text-[var(--viz-ink)]">
                    <p className="font-semibold mb-1">{short(d.date)}</p>
                    <p className="tabular-nums text-[var(--viz-ink-2)]">{d.new} new · {d.opted_out} opted out</p>
                  </div>
                );
              }} />
              <Bar dataKey="new" fill="var(--viz-1)" radius={[3, 3, 0, 0]} maxBarSize={10} isAnimationActive={false} />
              <Bar dataKey="opted_out" fill="var(--viz-2)" radius={[3, 3, 0, 0]} maxBarSize={10} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}
