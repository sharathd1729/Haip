"use client";
// The breakdown cards of the impact page: first reply by channel / by responder, after hours, the lead cohort, missed calls and
// lost reasons. Each card names the window it covers.
import { useState } from "react";
import { Card, CardBody, CardHeader, DataTable, Stat, Tabs, type Column } from "@/components/ui/kit";
import { duration, num, pct } from "@/components/dashboard/command/types";
import {
  CHANNEL_LABELS, RESPONDER_LABELS, formatPeriod, type ChannelKey, type ReplySummary, type ResponderKey, type ResponderSummary,
  type WindowMeasure,
} from "./types";

type Which = "with" | "before";
const WINDOW_TABS = [{ value: "with", label: "With HAIP" }, { value: "before", label: "Before (measured)" }];

type ChannelRow = ReplySummary & { key: ChannelKey };
type ResponderRow = ResponderSummary & { key: ResponderKey };

const channelCols: Column<ChannelRow>[] = [
  { key: "c", header: "Channel", cell: r => <span className="font-medium">{CHANNEL_LABELS[r.key]}</span> },
  { key: "t", header: "Guest turns", align: "right", cell: r => num(r.turns) },
  { key: "a", header: "Answered", align: "right", cell: r => pct(r.answered_pct) },
  { key: "m", header: "Median", align: "right", cell: r => duration(r.median_seconds) },
  { key: "p", header: "p90", align: "right", hideBelow: "sm", cell: r => duration(r.p90_seconds) },
  { key: "w5", header: "≤ 5 min", align: "right", hideBelow: "md", cell: r => pct(r.within_pct["5"]) },
  { key: "w15", header: "≤ 15 min", align: "right", hideBelow: "sm", cell: r => pct(r.within_pct["15"]) },
  { key: "w60", header: "≤ 1 h", align: "right", hideBelow: "md", cell: r => pct(r.within_pct["60"]) },
];
const responderCols: Column<ResponderRow>[] = [
  { key: "r", header: "Who replied first", cell: r => <span className="font-medium">{RESPONDER_LABELS[r.key]}</span> },
  { key: "a", header: "Turns answered", align: "right", cell: r => num(r.answered) },
  { key: "m", header: "Median", align: "right", cell: r => duration(r.median_seconds) },
  { key: "p", header: "p90", align: "right", hideBelow: "sm", cell: r => duration(r.p90_seconds) },
  { key: "w", header: "≤ 15 min", align: "right", hideBelow: "sm", cell: r => pct(r.within_15_pct) },
];

export function RepliesCard({ before, after }: { before: WindowMeasure; after: WindowMeasure }) {
  const [which, setWhich] = useState<Which>("with");
  const [split, setSplit] = useState("channel");
  const m = which === "with" ? after : before;
  const rep = m.replies;
  return (
    <Card>
      <CardHeader title="First reply to guests"
        description={`${formatPeriod(m.period)}. One guest turn = a guest message after our reply or after 24 h of silence. Personal WhatsApp is a read-only mirror of the team's phones.`}
        actions={<Tabs label="Window" value={which} onChange={v => setWhich(v as Which)} items={WINDOW_TABS} />} />
      <CardBody className="space-y-3">
        <Tabs label="Split" value={split} onChange={setSplit} items={[{ value: "channel", label: "By channel" }, { value: "responder", label: "By who replied" }]} />
        {split === "channel" ? (
          <DataTable columns={channelCols} rowKey={r => r.key} maxHeightClass="max-h-none"
            rows={(Object.keys(CHANNEL_LABELS) as ChannelKey[]).map(k => ({ key: k, ...rep.by_channel[k] }))}
            empty={{ title: "No guest messages in this window" }} />
        ) : (
          <DataTable columns={responderCols} rowKey={r => r.key} maxHeightClass="max-h-none"
            rows={(Object.keys(RESPONDER_LABELS) as ResponderKey[]).map(k => ({ key: k, ...rep.by_responder[k] }))} />
        )}
        <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
          {num(rep.all.turns)} guest turns, {num(rep.all.unanswered)} not answered.
          {rep.excluded_too_recent > 0 && ` ${num(rep.excluded_too_recent)} from the last hour are not counted yet.`}
          {rep.truncated && " Very many messages: only the first 200,000 were read."}
        </p>
      </CardBody>
    </Card>
  );
}

export function AfterHoursCard({ after }: { after: WindowMeasure }) {
  const ah = after.replies.after_hours;
  const hint = formatPeriod(after.period);
  return (
    <Card>
      <CardHeader title="After hours" description="Guest turns that started outside business hours (workspace hours, else 9–21 weekdays IST)." />
      <CardBody className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Stat label="After-hours guest turns" value={num(ah.turns)} hint={hint} />
        <Stat label="Answered within 15 min" value={pct(ah.within_15_pct)} hint={hint} />
        <Stat label="Answered by the AI on its own" value={pct(ah.ai_share_pct)} hint={`${num(ah.answered_by_ai)} of ${num(ah.answered)} answered`} />
      </CardBody>
    </Card>
  );
}

function Compare({ rows, before, after }: { rows: { label: string; b: string; a: string }[]; before: WindowMeasure; after: WindowMeasure }) {
  return (
    <table className="w-full text-[13.5px]">
      <thead><tr className="text-left text-[12px] text-[var(--haip-fg-subtle)]">
        <th className="py-2 font-semibold" />
        <th className="py-2 text-right font-semibold">Before (measured)<span className="block font-normal">{formatPeriod(before.period)}</span></th>
        <th className="py-2 text-right font-semibold">With HAIP<span className="block font-normal">{formatPeriod(after.period)}</span></th>
      </tr></thead>
      <tbody>{rows.map(r => (
        <tr key={r.label} className="border-t border-[var(--haip-border)]">
          <td className="py-2 pr-2">{r.label}</td><td className="py-2 text-right tabular-nums">{r.b}</td><td className="py-2 text-right tabular-nums">{r.a}</td>
        </tr>))}
      </tbody>
    </table>
  );
}

const withPct = (n: number, p: number | null) => (p == null ? num(n) : `${num(n)} (${pct(p)})`);

export function CohortCard({ before, after }: { before: WindowMeasure; after: WindowMeasure }) {
  const fb = before.funnel, fa = after.funnel;
  return (
    <Card>
      <CardHeader title="Enquiries, leads, quotes, bookings"
        description="Leads are people with a usable phone number. Quoted and booked follow the people who became leads in the window, so far (recent windows are still maturing). Enquiry records are not divided by leads." />
      <CardBody>
        <Compare before={before} after={after} rows={[
          { label: "Enquiry records", b: num(fb.enquiries), a: num(fa.enquiries) },
          { label: "New leads", b: num(fb.leads), a: num(fa.leads) },
          { label: "Of them quoted", b: withPct(fb.quoted, fb.lead_to_quote_pct), a: withPct(fa.quoted, fa.lead_to_quote_pct) },
          { label: "Of them booked", b: withPct(fb.booked, fb.lead_to_booking_pct), a: withPct(fa.booked, fa.lead_to_booking_pct) },
        ]} />
      </CardBody>
    </Card>
  );
}

export function CallsCard({ before, after }: { before: WindowMeasure; after: WindowMeasure }) {
  const mb = before.missed_calls, ma = after.missed_calls;
  return (
    <Card>
      <CardHeader title="Missed calls" description="Inbound calls nobody answered, and whether the guest was called back (whenever that happened)." />
      <CardBody>
        <Compare before={before} after={after} rows={[
          { label: "Missed calls", b: num(mb.missed), a: num(ma.missed) },
          { label: "Called back", b: withPct(mb.returned, mb.returned_pct), a: withPct(ma.returned, ma.returned_pct) },
          { label: "Median time to call back", b: duration(mb.median_callback_seconds), a: duration(ma.median_callback_seconds) },
          { label: "Called back within 1 hour", b: pct(mb.within_60_pct), a: pct(ma.within_60_pct) },
        ]} />
      </CardBody>
    </Card>
  );
}

export function LostCard({ before, after }: { before: WindowMeasure; after: WindowMeasure }) {
  const reasons = Array.from(new Set([...after.lost.by_reason, ...before.lost.by_reason].map(r => r.label)));
  const count = (m: WindowMeasure, label: string) => num(m.lost.by_reason.find(r => r.label === label)?.count ?? 0);
  return (
    <Card>
      <CardHeader title="Enquiries lost, and why" description="Enquiry records moved to a lost stage in the window, by the reason recorded on them." />
      <CardBody>
        {reasons.length === 0
          ? <p className="text-[13.5px] text-[var(--haip-fg-subtle)]">No enquiries were marked lost in either window.</p>
          : <Compare before={before} after={after} rows={[
              ...reasons.map(label => ({ label, b: count(before, label), a: count(after, label) })),
              { label: "Total", b: num(before.lost.total), a: num(after.lost.total) },
            ]} />}
      </CardBody>
    </Card>
  );
}
