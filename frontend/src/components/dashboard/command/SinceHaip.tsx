"use client";
// "Since HAIP": five headline figures, the latest N days vs the same number of days just before go-live
// (GET /dashboard/impact/since-haip, backend/app/services/impact_since.py). Every "before" figure says where it came from;
// an empty baseline reads "No data" with no change (never -100%). The full view with owner baselines is /dashboard/impact.
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Lock } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, StatusPill, type Tone } from "@/components/ui/kit";
import { duration, inr, num, periodLabel } from "./types";

export interface SinceTileOpen {
  key: string; label: string; unit: "count" | "inr" | "minutes" | "%"; lower_is_better: boolean; definition: string;
  restricted: false;
  before: { value: number | null; n: number | null; has_data: boolean; source: string };
  with: { value: number | null };
  change: { kind: "pct" | "points"; value: number; better: boolean | null } | null;
}
export type SinceTile = SinceTileOpen | { key: string; label: string; restricted: true };
interface Window { from: string; to: string; days: number }
export interface SinceHaipView {
  needs_go_live: boolean; go_live: string | null; days: number; can_edit: boolean;
  windows?: { before: Window; with: Window };
  tiles?: SinceTile[];
}

export function formatValue(unit: SinceTileOpen["unit"], v: number | null): string {
  if (v == null) return "—";
  if (unit === "inr") return inr(v);
  if (unit === "minutes") return duration(v * 60);
  if (unit === "%") return `${v}%`;
  return num(v);
}

export function changeText(c: NonNullable<SinceTileOpen["change"]>): { text: string; tone: Tone } {
  const sign = c.value > 0 ? "+" : "";
  const text = c.kind === "points" ? `${sign}${c.value} pts` : `${sign}${c.value}%`;
  return { text, tone: c.better == null ? "neutral" : c.better ? "success" : "danger" };
}

function Tile({ t }: { t: SinceTile }) {
  if (t.restricted) {
    return (
      <li className="min-w-0 rounded-xl bg-[var(--haip-surface)] px-3 py-3">
        <p className="text-[12.5px] font-medium text-[var(--haip-fg-muted)]">{t.label}</p>
        <p className="mt-1.5 flex items-center gap-1.5 text-[12.5px] text-[var(--haip-fg-subtle)]"><Lock size={13} aria-hidden />Hidden for your role</p>
      </li>
    );
  }
  const change = t.change ? changeText(t.change) : null;
  return (
    <li className="min-w-0 rounded-xl bg-[var(--haip-surface)] px-3 py-3" title={t.definition}>
      <p className="text-[12.5px] font-medium text-[var(--haip-fg-muted)]">{t.label}</p>
      <p className="mt-1 font-[family-name:var(--font-display)] text-[22px] font-semibold leading-tight tabular-nums text-[var(--haip-fg)] [overflow-wrap:anywhere]">
        {formatValue(t.unit, t.with.value)}
      </p>
      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-[var(--haip-fg-2)]">
        <span>Before: <span className="font-semibold tabular-nums">{t.before.has_data ? formatValue(t.unit, t.before.value) : "No data"}</span></span>
        {change && <StatusPill tone={change.tone}>{change.text}</StatusPill>}
      </p>
      <p className="mt-1 text-[11.5px] leading-snug text-[var(--haip-fg-subtle)]">{t.before.source}</p>
    </li>
  );
}

export function SinceHaip() {
  const { data, isLoading, isError, refetch } = useQuery<SinceHaipView>({
    queryKey: ["impact-since-haip"],
    queryFn: () => api.get("/dashboard/impact/since-haip").then(r => r.data),
    staleTime: 5 * 60_000,
  });

  const w = data?.windows;
  const description = w
    ? `${periodLabel(w.with.from, w.with.to)} vs the ${w.before.days} days before go-live (${periodLabel(w.before.from, w.before.to)}) · IST`
    : "Before go-live vs since, over the same number of days";

  let body;
  if (isLoading) {
    body = <div className="grid grid-cols-2 gap-2 lg:grid-cols-5" aria-busy="true">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-28" />)}</div>;
  } else if (isError) {
    body = (
      <p role="alert" className="text-[13px] text-[var(--haip-fg-2)]">
        The before / after numbers didn’t load.{" "}
        <button type="button" onClick={() => refetch()} className="inline-flex min-h-11 items-center font-semibold text-primary underline lg:min-h-0">Try again</button>
      </p>
    );
  } else if (!data || data.needs_go_live || !Array.isArray(data.tiles)) {
    body = (
      <p className="text-[13px] text-[var(--haip-fg-2)]">
        {data?.can_edit
          ? <>Set the date HAIP went live to compare before and after. <Link href="/dashboard/impact" className="inline-flex min-h-11 items-center font-semibold text-primary hover:underline lg:min-h-0">Set the go-live date</Link></>
          : "The owner hasn’t set the date HAIP went live yet, so there is nothing to compare."}
      </p>
    );
  } else {
    body = <ul className="grid grid-cols-1 gap-2 min-[400px]:grid-cols-2 lg:grid-cols-5">{data.tiles.map(t => <Tile key={t.key} t={t} />)}</ul>;
  }

  return (
    <Card aria-labelledby="since-haip-title">
      <CardHeader
        title={<span id="since-haip-title">Since HAIP</span>}
        description={description}
        actions={<Link href="/dashboard/impact" className="inline-flex min-h-11 items-center text-[12.5px] font-semibold text-primary hover:underline lg:min-h-0">Full before / after view</Link>}
      />
      <CardBody>{body}</CardBody>
    </Card>
  );
}
