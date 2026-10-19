"use client";
// Three cards: when leads want to travel (by check-in week; Active enquiries | Booked), where leads came from (first touch, with
// Organic calls as its own source) and leads by stage (Lost by reason, spam counted apart). Only people with a phone number count.
import { useState } from "react";
import { Tabs, StatusPill, type Tone } from "@/components/ui/kit";
import { BarRow, Block } from "./OwnerParts";
import { weekLabel, type OwnerBlock, type Stages, type Travel } from "./owner";
import type { SourceRow } from "./types";

export function TravelCard({ travel }: { travel: Travel }) {
  const [tab, setTab] = useState<"active" | "booked">("active");
  const showBooked = tab === "booked" && !travel.booked_restricted;
  const values = travel.weeks.map(w => (showBooked ? w.booked ?? 0 : w.active));
  const max = Math.max(1, ...values);
  const total = values.reduce((a, b) => a + b, 0);
  return (
    <Block title="When leads want to travel" period="by check-in week, from this week">
      <Tabs label="Show" value={tab} onChange={v => setTab(v as "active" | "booked")} className="mb-3"
        items={[{ value: "active", label: "Active enquiries" }, ...(travel.booked_restricted ? [] : [{ value: "booked", label: "Booked" }])]} />
      {total === 0 ? (
        <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">{showBooked ? "No bookings ahead yet." : "No open lead has given a check-in date yet."}</p>
      ) : (
        <div className="space-y-2">
          {travel.weeks.map((w, i) => <BarRow key={w.start ?? "later"} label={weekLabel(w.start, i)} value={values[i]} max={max} tone={showBooked ? "primary" : "series2"} />)}
        </div>
      )}
      <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">{showBooked ? travel.booked_basis : travel.active_basis}.</p>
    </Block>
  );
}

export function SourcesCard({ sources, period }: { sources: SourceRow[]; period: string }) {
  const max = Math.max(1, ...sources.map(s => s.leads));
  return (
    <Block title="Where leads came from" period={`${period} · first contact`}>
      {sources.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">No new leads in this period.</p>
      ) : (
        <div className="space-y-2">{sources.map(s => <BarRow key={s.key} label={s.label} value={s.leads} max={max} />)}</div>
      )}
      <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">New leads (people with a phone number) by how they first got in touch. Organic calls = called the number directly, no ad behind it.</p>
    </Block>
  );
}

function toneOf(s: Stages["stages"][number]): Tone {
  if (s.won) return "success";
  if (s.lost) return "danger";
  if (s.category === "valid") return "info";
  if (s.category === "marketing") return "brand";
  return "warning";
}

export function StagesCard({ stages, period }: { stages: Stages; period: string }) {
  const shown = stages.stages.filter(s => s.count > 0 || s.category === "valid");
  const any = stages.stages.some(s => s.count > 0) || stages.unqualified > 0;
  return (
    <Block title="Leads by stage" period={`${period} · enquiries from leads`}>
      {!any ? (
        <p className="py-6 text-center text-[13px] text-[var(--haip-fg-subtle)]">No enquiries from leads in this period.</p>
      ) : (
        <>
          <ul className="flex flex-wrap gap-x-3 gap-y-2">
            {shown.map(s => (
              <li key={s.key} className="flex items-center gap-1.5"><StatusPill tone={toneOf(s)}>{s.label}</StatusPill><b className="tabular-nums text-[var(--haip-fg)]">{s.count}</b></li>
            ))}
            <li className="flex items-center gap-1.5"><StatusPill tone="neutral">Unqualified</StatusPill><b className="tabular-nums text-[var(--haip-fg)]">{stages.unqualified}</b></li>
          </ul>
          <p className="mb-1 mt-3 text-[12.5px] font-medium text-[var(--haip-fg-2)]">Lost, by reason</p>
          {stages.lost_by_reason.length === 0 ? <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">None lost in this period.</p> : (
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-[var(--haip-fg-subtle)]">
              {stages.lost_by_reason.map(l => <li key={l.reason}>{l.label} <b className="tabular-nums text-[var(--haip-fg)]">{l.count}</b></li>)}
            </ul>
          )}
        </>
      )}
      <p className="mt-3 text-[12px] text-[var(--haip-fg-subtle)]">Unqualified is counted only once a lead shared a number; a DM that never did is not counted. One person with two enquiries counts twice.</p>
    </Block>
  );
}

/** The three cards as one responsive row (one column on a phone, three from the laptop width). */
export function LeadsRowCards({ owner, sources, period }: { owner: OwnerBlock; sources: SourceRow[]; period: string }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <TravelCard travel={owner.travel} />
      <SourcesCard sources={sources} period={period} />
      <StagesCard stages={owner.stages} period={period} />
    </div>
  );
}
