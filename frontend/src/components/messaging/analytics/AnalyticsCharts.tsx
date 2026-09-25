"use client";
import { useState, type ReactNode } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertCircle, Table2, BarChart3 } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { fmt, hourLabel, pct, shortDate, type DayRow, type FailureRow, type HourRow, type Totals } from "./analyticsTypes";

const AXIS = { fontSize: 11, fill: "var(--viz-ink-3)" } as const;

// ─── Card with a "view as table" switch ──────────────────────────────────────

export function ChartCard({ title, subtitle, legend, table, children, className }: {
  title: string; subtitle?: string; legend?: ReactNode;
  table?: { columns: string[]; rows: (string | number)[][] };
  children: ReactNode; className?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className={cn("wa-viz rounded-2xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-5", className)} aria-label={title}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-[var(--viz-ink)]">{title}</h3>
          {subtitle && <p className="text-xs text-[var(--viz-ink-2)] mt-0.5">{subtitle}</p>}
        </div>
        {table && (
          <button type="button" onClick={() => setAsTable(v => !v)} aria-pressed={asTable}
            className="flex items-center gap-1.5 text-[11px] font-medium text-[var(--viz-ink-2)] border border-[var(--haip-border)] rounded-lg px-2 py-1 hover:bg-[var(--haip-surface)] flex-shrink-0">
            {asTable ? <BarChart3 size={12} /> : <Table2 size={12} />} {asTable ? "Chart" : "Table"}
          </button>
        )}
      </div>
      {legend && !asTable && <div className="flex flex-wrap gap-x-4 gap-y-1 mb-2 text-xs text-[var(--viz-ink-2)]">{legend}</div>}
      {asTable && table ? (
        <div className="max-h-64 overflow-auto rounded-lg border border-[var(--haip-border)]">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-[var(--haip-surface)] text-[var(--viz-ink-2)]">
              <tr>{table.columns.map((c, i) => <th key={c} className={cn("font-medium px-3 py-1.5", i === 0 ? "text-left" : "text-right")}>{c}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-[var(--haip-border)] text-[var(--viz-ink)]">
              {table.rows.map((r, i) => (
                <tr key={i}>{r.map((c, j) => <td key={j} className={cn("px-3 py-1.5", j === 0 ? "text-left" : "text-right")}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : children}
    </section>
  );
}

function Swatch({ color, label, line }: { color: string; label: string; line?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className={cn("inline-block", line ? "h-[3px] w-4 rounded-full" : "h-2.5 w-2.5 rounded-[3px]")} style={{ background: color }} />
      {label}
    </span>
  );
}

function TipBox({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--haip-border)] bg-[var(--viz-surface)] px-3 py-2 shadow-md text-xs text-[var(--viz-ink)]">
      <p className="font-semibold mb-1">{title}</p>
      <div className="space-y-0.5 tabular-nums text-[var(--viz-ink-2)]">{children}</div>
    </div>
  );
}

// ─── Messages per day ────────────────────────────────────────────────────────

export function VolumeChart({ daily }: { daily: DayRow[] }) {
  const empty = daily.every(d => d.sent + d.failed === 0);
  return (
    <ChartCard
      title="Messages sent per day"
      subtitle="Every message Meta accepted, by the day it was sent"
      table={{ columns: ["Day", "Sent", "Delivered", "Read", "Failed"], rows: daily.map(d => [shortDate(d.date), fmt(d.sent), fmt(d.delivered), fmt(d.read), fmt(d.failed)]) }}
    >
      {empty ? <Empty text="Nothing sent in this period." /> : (
        <div className="h-56" role="img" aria-label="Column chart of messages sent per day">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={daily} margin={{ top: 8, right: 4, bottom: 0, left: -12 }}>
              <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
              <XAxis dataKey="date" tickFormatter={shortDate} tick={AXIS} axisLine={false} tickLine={false} minTickGap={28} />
              <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip cursor={{ fill: "var(--viz-grid)" }} content={({ active, payload }) => {
                const d = active && payload?.[0]?.payload as DayRow | undefined;
                if (!d) return null;
                return (
                  <TipBox title={shortDate(d.date)}>
                    <p>Sent {fmt(d.sent)}</p><p>Delivered {fmt(d.delivered)}</p><p>Read {fmt(d.read)}</p>
                    {d.failed > 0 && <p>Failed {fmt(d.failed)}</p>}
                  </TipBox>
                );
              }} />
              <Bar dataKey="sent" fill="var(--viz-1)" radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}

// ─── Delivery + read rate over time ──────────────────────────────────────────

export function RateChart({ daily }: { daily: DayRow[] }) {
  const empty = daily.every(d => d.delivery_rate === null);
  return (
    <ChartCard
      title="Delivery and read rate"
      subtitle="Share of each sending day's messages that arrived, and that were opened"
      legend={<><Swatch line color="var(--viz-1)" label="Delivered (of sent)" /><Swatch line color="var(--viz-2)" label="Read (of delivered)" /></>}
      table={{ columns: ["Day", "Delivered", "Read"], rows: daily.map(d => [shortDate(d.date), pct(d.delivery_rate), pct(d.read_rate)]) }}
    >
      {empty ? <Empty text="Rates appear once messages have been sent." /> : (
        <div className="h-56" role="img" aria-label="Line chart of delivery and read rate per day">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={daily} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
              <XAxis dataKey="date" tickFormatter={shortDate} tick={AXIS} axisLine={false} tickLine={false} minTickGap={28} />
              <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={v => `${v}%`} tick={AXIS} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ stroke: "var(--viz-ink-3)", strokeDasharray: "3 3" }} content={({ active, payload }) => {
                const d = active && payload?.[0]?.payload as DayRow | undefined;
                if (!d) return null;
                return (
                  <TipBox title={shortDate(d.date)}>
                    <p><Swatch line color="var(--viz-1)" label={`Delivered ${pct(d.delivery_rate)}`} /></p>
                    <p><Swatch line color="var(--viz-2)" label={`Read ${pct(d.read_rate)}`} /></p>
                    <p>{fmt(d.sent)} sent that day</p>
                  </TipBox>
                );
              }} />
              <Line type="monotone" dataKey="delivery_rate" stroke="var(--viz-1)" strokeWidth={2} dot={{ r: 3, fill: "var(--viz-1)", stroke: "var(--viz-surface)", strokeWidth: 1.5 }} activeDot={{ r: 5, stroke: "var(--viz-surface)", strokeWidth: 2 }} connectNulls isAnimationActive={false} />
              <Line type="monotone" dataKey="read_rate" stroke="var(--viz-2)" strokeWidth={2} dot={{ r: 3, fill: "var(--viz-2)", stroke: "var(--viz-surface)", strokeWidth: 1.5 }} activeDot={{ r: 5, stroke: "var(--viz-surface)", strokeWidth: 2 }} connectNulls isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}

// ─── Funnel: sent → delivered → read, with failures kept apart ───────────────

export function Funnel({ totals }: { totals: Totals }) {
  const max = Math.max(totals.sent, 1);
  const steps = [
    { label: "Sent", value: totals.sent, note: "accepted by WhatsApp", color: "var(--viz-seq-1)" },
    { label: "Delivered", value: totals.delivered, note: pct(totals.delivery_rate) + " of sent", color: "var(--viz-seq-2)" },
    { label: "Read", value: totals.read, note: pct(totals.read_rate) + " of delivered", color: "var(--viz-seq-3)" },
  ];
  return (
    <ChartCard title="From sent to read" subtitle="Where messages drop off"
      table={{ columns: ["Step", "Messages", "Rate"], rows: [["Sent", fmt(totals.sent), ""], ["Delivered", fmt(totals.delivered), pct(totals.delivery_rate)], ["Read", fmt(totals.read), pct(totals.read_rate)], ["Failed", fmt(totals.failed), pct(totals.failure_rate)]] }}>
      <ul className="space-y-3">
        {steps.map(s => (
          <li key={s.label}>
            <div className="flex items-baseline justify-between text-xs mb-1">
              <span className="font-medium text-[var(--viz-ink)]">{s.label}</span>
              <span className="tabular-nums text-[var(--viz-ink-2)]"><strong className="text-[var(--viz-ink)]">{fmt(s.value)}</strong> · {s.note}</span>
            </div>
            <div className="h-3 rounded-[4px] bg-[var(--viz-grid)] overflow-hidden" role="presentation">
              <div className="h-full rounded-[4px]" style={{ width: `${Math.max((s.value / max) * 100, s.value > 0 ? 1.5 : 0)}%`, background: s.color }} />
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-4 pt-3 border-t border-[var(--haip-border)] flex items-center gap-2 text-xs">
        <AlertCircle size={14} className="text-[var(--viz-fail)] flex-shrink-0" aria-hidden />
        <span className="font-medium text-[var(--viz-ink)]">Failed</span>
        <span className="ml-auto tabular-nums text-[var(--viz-ink-2)]"><strong className="text-[var(--viz-ink)]">{fmt(totals.failed)}</strong> · {pct(totals.failure_rate)} of attempts</span>
      </div>
    </ChartCard>
  );
}

// ─── Why messages failed ─────────────────────────────────────────────────────

export function FailureBars({ failures }: { failures: FailureRow[] }) {
  const max = Math.max(...failures.map(f => f.count), 1);
  return (
    <ChartCard title="Why messages failed" subtitle="Most common reasons in this period"
      table={{ columns: ["Reason", "Messages"], rows: failures.map(f => [f.label, fmt(f.count)]) }}>
      {failures.length === 0 ? <Empty text="No failed messages. Nice." /> : (
        <ul className="space-y-3">
          {failures.map(f => (
            <li key={f.group}>
              <div className="flex items-baseline justify-between text-xs mb-1">
                <span className="font-medium text-[var(--viz-ink)]">{f.label}</span>
                <strong className="tabular-nums text-[var(--viz-ink)]">{fmt(f.count)}</strong>
              </div>
              <div className="h-2.5 rounded-[4px] bg-[var(--viz-grid)] overflow-hidden" role="presentation">
                <div className="h-full rounded-[4px]" style={{ width: `${(f.count / max) * 100}%`, background: "var(--viz-seq-2)" }} />
              </div>
              <p className="text-[11px] text-[var(--viz-ink-2)] mt-1 leading-snug">{f.reason}{f.hint ? ` — ${f.hint}` : ""}</p>
            </li>
          ))}
        </ul>
      )}
    </ChartCard>
  );
}

// ─── Best time to send ───────────────────────────────────────────────────────

export function HourChart({ hours, best }: { hours: HourRow[]; best: number | null }) {
  const data = hours.map(h => ({ ...h, rate: h.read_rate ?? 0 }));
  const any = hours.some(h => h.sent > 0);
  return (
    <ChartCard
      title="Best time to send"
      subtitle={best !== null ? `Read rate by the hour of sending (India time). ${hourLabel(best)} does best.` : "Read rate by the hour of sending (India time)"}
      table={{ columns: ["Hour", "Sent", "Read", "Read rate"], rows: hours.filter(h => h.sent > 0).map(h => [hourLabel(h.hour), fmt(h.sent), fmt(h.read), pct(h.read_rate)]) }}
    >
      {!any ? <Empty text="Send some messages to see when they get read." /> : (
        <div className="h-44" role="img" aria-label="Column chart of read rate by hour of sending">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -12 }}>
              <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
              <XAxis dataKey="hour" tickFormatter={hourLabel} tick={AXIS} axisLine={false} tickLine={false} interval={2} />
              <YAxis domain={[0, 100]} ticks={[0, 50, 100]} tickFormatter={v => `${v}%`} tick={AXIS} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "var(--viz-grid)" }} content={({ active, payload }) => {
                const h = active && payload?.[0]?.payload as HourRow | undefined;
                if (!h) return null;
                return <TipBox title={hourLabel(h.hour)}><p>{h.sent ? `${pct(h.read_rate)} read` : "Nothing sent"}</p>{h.sent > 0 && <p>{fmt(h.read)} of {fmt(h.sent)} sent</p>}</TipBox>;
              }} />
              <Bar dataKey="rate" radius={[4, 4, 0, 0]} maxBarSize={18} isAnimationActive={false}>
                {data.map(h => <Cell key={h.hour} fill={h.hour === best ? "var(--viz-1)" : "var(--viz-muted)"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="h-40 flex items-center justify-center text-xs text-[var(--viz-ink-3)]">{text}</div>;
}
