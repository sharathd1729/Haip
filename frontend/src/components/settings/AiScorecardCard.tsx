"use client";
// Settings > AI: the honest AI scorecard (GET /ai/scorecard?period=7d|30d, owner/manager). How much the AI did alone, when it
// asked a person and why, how fast people answered against the SLA, and leads with vs without a consult. Every number names its
// period; an empty period says "No data", never 0% or 100%.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, Stat, Tabs } from "@/components/ui/kit";

type Share = number | null;
export type Scorecard = {
  period: "7d" | "30d";
  ai_replies: { sent_alone: number; approved_as_written: number; edited: number; rejected: number; decided: number; no_edit_share: Share };
  consults: { opened: number; expired: number; by_reason: { code: string; label: string; count: number }[] };
  answer_minutes: { answered: number; median: number | null; p90: number | null; sla_minutes: number; inside_sla_share: Share };
  held_back: { total: number; reasons: { reason: string; count: number }[] };
  conversion: { with_consult: { leads: number; won: number; rate: Share }; without_consult: { leads: number; won: number; rate: Share } };
};

export const pct = (v: Share) => (v == null ? "No data" : `${Math.round(v * 100)}%`);
const mins = (v: number | null) => (v == null ? "No data" : `${v} min`);

export function AiScorecardCard() {
  const [period, setPeriod] = useState<"7d" | "30d">("7d");
  const { data, isPending, isError, refetch } = useQuery<Scorecard>({
    queryKey: ["ai-scorecard", period],
    queryFn: () => api.get("/ai/scorecard", { params: { period } }).then(r => r.data),
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1,
  });
  const span = period === "7d" ? "last 7 days" : "last 30 days";
  return (
    <Card>
      <CardHeader title="AI scorecard" description="What the AI did alone, when it asked you, and how fast the team answered."
        actions={<Tabs label="Period" value={period} onChange={v => setPeriod(v as "7d" | "30d")}
          items={[{ value: "7d", label: "7 days" }, { value: "30d", label: "30 days" }]} />} />
      <CardBody className="space-y-4">
        {isError ? (
          <p className="text-sm text-[var(--haip-fg-subtle)]">Couldn't load the scorecard (owners and managers only). <button type="button" className="font-semibold text-primary underline" onClick={() => refetch()}>Try again</button></p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat loading={isPending} label="Replies sent with no edit" value={data ? pct(data.ai_replies.no_edit_share) : ""}
                hint={data ? `${data.ai_replies.sent_alone + data.ai_replies.approved_as_written} of ${data.ai_replies.decided} decided · ${span}` : span} />
              <Stat loading={isPending} label="Questions the AI asked you" value={data?.consults.opened ?? ""}
                hint={data ? `${data.consults.expired} expired unanswered · ${span}` : span} />
              <Stat loading={isPending} label="Median answer time" value={data ? mins(data.answer_minutes.median) : ""}
                hint={data ? `90th percentile ${mins(data.answer_minutes.p90)} · ${span}` : span} />
              <Stat loading={isPending} label={data ? `Answered inside ${data.answer_minutes.sla_minutes} min` : "Answered inside the SLA"}
                value={data ? pct(data.answer_minutes.inside_sla_share) : ""} hint={data ? `${data.answer_minutes.answered} answered · ${span}` : span} />
            </div>
            {data && (
              <div className="grid gap-4 lg:grid-cols-3">
                <section>
                  <h3 className="text-sm font-semibold text-[var(--haip-fg)]">Why it asked ({span})</h3>
                  {data.consults.by_reason.length ? (
                    <ul className="mt-1 space-y-1 text-[13px] text-[var(--haip-fg-2)]">
                      {data.consults.by_reason.slice(0, 8).map(r => <li key={r.code} className="flex justify-between gap-2"><span className="min-w-0 break-words">{r.label}</span><span className="num">{r.count}</span></li>)}
                    </ul>
                  ) : <p className="mt-1 text-[13px] text-[var(--haip-fg-subtle)]">No questions in this period.</p>}
                </section>
                <section>
                  <h3 className="text-sm font-semibold text-[var(--haip-fg)]">Replies held back ({span})</h3>
                  {data.held_back.reasons.length ? (
                    <ul className="mt-1 space-y-1 text-[13px] text-[var(--haip-fg-2)]">
                      {data.held_back.reasons.map(r => <li key={r.reason} className="flex justify-between gap-2"><span className="min-w-0 break-words">{r.reason}</span><span className="num">{r.count}</span></li>)}
                    </ul>
                  ) : <p className="mt-1 text-[13px] text-[var(--haip-fg-subtle)]">Nothing held back in this period.</p>}
                  <p className="mt-2 text-[12px] text-[var(--haip-fg-subtle)]">Staff: {data.ai_replies.approved_as_written} approved as written, {data.ai_replies.edited} edited, {data.ai_replies.rejected} rejected.</p>
                </section>
                <section>
                  <h3 className="text-sm font-semibold text-[var(--haip-fg)]">Leads won ({span}, enquiries created)</h3>
                  <ul className="mt-1 space-y-1 text-[13px] text-[var(--haip-fg-2)]">
                    <li className="flex justify-between gap-2"><span>After the AI asked you</span><span className="num">{data.conversion.with_consult.won}/{data.conversion.with_consult.leads} · {pct(data.conversion.with_consult.rate)}</span></li>
                    <li className="flex justify-between gap-2"><span>Without a question</span><span className="num">{data.conversion.without_consult.won}/{data.conversion.without_consult.leads} · {pct(data.conversion.without_consult.rate)}</span></li>
                  </ul>
                  <p className="mt-2 text-[12px] text-[var(--haip-fg-subtle)]">Small numbers are not a trend.</p>
                </section>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
