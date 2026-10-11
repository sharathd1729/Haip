"use client";
// One daily series as bars, with a switch for which measure. One series, so no legend: the title names it and the
// busiest day is labelled directly.
import { useState } from "react";
import { formatINR } from "@/lib/utils";
import { Card, CardBody, CardHeader, FilterChip } from "@/components/ui/kit";
import { num, shortDate, type Summary } from "./ads";

const MEASURES = [
  { key: "spend", label: "Spend", fmt: (n: number) => formatINR(n) },
  { key: "conversations", label: "Chats started", fmt: (n: number) => num(n) },
  { key: "clicks", label: "Clicks", fmt: (n: number) => num(n) },
  { key: "impressions", label: "Impressions", fmt: (n: number) => num(n) },
] as const;

export function DailyChart({ daily, rangeLabel }: { daily: Summary["daily"]; rangeLabel: string }) {
  const [key, setKey] = useState<(typeof MEASURES)[number]["key"]>("spend");
  if (daily.length < 2) return null;
  const m = MEASURES.find(x => x.key === key)!;
  const values = daily.map(d => d[key]);
  const max = Math.max(...values, 1);
  const topIdx = values.indexOf(Math.max(...values));
  const W = 700, H = 120, gap = daily.length > 120 ? 1 : 3;
  const bw = Math.max(1.5, (W - gap * (daily.length - 1)) / daily.length);
  const top = daily[topIdx];

  return (
    <Card>
      <CardHeader title={`Daily ${m.label.toLowerCase()}`} description={rangeLabel}
        actions={<div className="flex flex-wrap gap-1.5">{MEASURES.map(x => (
          <FilterChip key={x.key} active={key === x.key} onClick={() => setKey(x.key)}>{x.label}</FilterChip>))}</div>} />
      <CardBody>
        <figure className="m-0">
          <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img"
            aria-label={`Daily ${m.label.toLowerCase()}. Highest day ${shortDate(top.date)}, ${m.fmt(values[topIdx])}.`}>
            {[0.5, 1].map(f => <line key={f} x1={0} x2={W} y1={H - H * f} y2={H - H * f} className="stroke-[var(--haip-border)]" strokeWidth={1} />)}
            {daily.map((d, i) => {
              const h = Math.max(1, (values[i] / max) * (H - 4));
              return (
                <rect key={d.date} x={i * (bw + gap)} y={H - h} width={bw} height={h} rx={Math.min(2, bw / 2)}
                  className={i === topIdx ? "fill-primary" : "fill-primary/45"}>
                  <title>{`${shortDate(d.date)}: ${m.fmt(values[i])}`}</title>
                </rect>
              );
            })}
            <text x={0} y={H + 14} className="fill-[var(--haip-fg-subtle)] text-[11px]">{shortDate(daily[0].date)}</text>
            <text x={W} y={H + 14} textAnchor="end" className="fill-[var(--haip-fg-subtle)] text-[11px]">{shortDate(daily[daily.length - 1].date)}</text>
          </svg>
          <figcaption className="mt-1 text-xs text-[var(--haip-fg-subtle)]">Highest day: {m.fmt(values[topIdx])} on {shortDate(top.date)}</figcaption>
        </figure>
      </CardBody>
    </Card>
  );
}
