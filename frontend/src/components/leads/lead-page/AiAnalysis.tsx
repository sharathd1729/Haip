"use client";
// "Full analysis": the structured AI read of the lead (the old page's AI analysis tab), kept reachable from the
// details panel. Read from inquiries.ai_analysis; nothing here calls a model.
import type { ReactNode } from "react";
import { RefreshCw } from "@/lib/icons";
import { StatusPill, type Tone } from "@/components/ui/page";
import { ActionableInsights } from "@/components/ai/ActionableInsights";
import type { AiAnalysis as Analysis } from "./types";

const TONE: Record<string, Tone> = { positive: "success", neutral: "neutral", hesitant: "warning", negative: "danger", high: "danger", medium: "warning", low: "neutral" };
const BOOKING: Record<string, string> = { none: "No booking yet", confirmed: "Booked", checked_in: "Checked in", checked_out: "Stay completed", cancelled: "Booking cancelled" };
const PAY: Record<string, string> = { unpaid: "no payment yet", partial: "part-paid", paid: "fully paid" };

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--haip-border)] py-2.5 last:border-0">
      <span className="shrink-0 pt-0.5 text-[12px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">{label}</span>
      <div className="min-w-0 text-right text-[13.5px] text-[var(--haip-fg)]">{children}</div>
    </div>
  );
}

export function AiAnalysis({ analysis, onRefresh, refreshing }: { analysis: Analysis | null | undefined; onRefresh: () => void; refreshing: boolean }) {
  if (!analysis) {
    return (
      <div className="grid justify-items-center gap-2 rounded-xl border border-dashed border-[var(--haip-border)] p-5 text-center">
        <p className="text-[13px] text-[var(--haip-fg-subtle)]">The structured analysis (intent, sentiment, objections, urgency) appears after the summary next regenerates.</p>
        <button type="button" onClick={onRefresh} disabled={refreshing}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-[var(--haip-border-strong)] px-3 text-[13px] font-semibold text-primary disabled:opacity-60">
          <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} aria-hidden /> Generate now
        </button>
      </div>
    );
  }
  return (
    <div className="grid gap-3">
      <ActionableInsights insights={analysis} />
      <div className="rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3.5 py-1">
        <Row label="Intent">{analysis.intent || "—"}</Row>
        <Row label="Sentiment"><StatusPill tone={TONE[analysis.sentiment ?? ""] ?? "neutral"}>{analysis.sentiment || "unknown"}</StatusPill></Row>
        <Row label="Objection">{analysis.objection || "None detected"}</Row>
        <Row label="Reply urgency"><StatusPill tone={TONE[analysis.reply_urgency ?? ""] ?? "neutral"}>{analysis.reply_urgency || "unknown"}</StatusPill></Row>
        {!!analysis.unanswered_questions?.length && <Row label="Not answered yet">{analysis.unanswered_questions.join(" · ")}</Row>}
        {!!analysis.requirements?.length && <Row label="Asked for">{analysis.requirements.join(" · ")}</Row>}
        {analysis.follow_up && <Row label="Follow up">{analysis.follow_up}</Row>}
        {analysis.booking_status && (
          <Row label="Booking">
            {BOOKING[analysis.booking_status.state] ?? analysis.booking_status.state}
            {analysis.booking_status.payment ? ` — ${PAY[analysis.booking_status.payment] ?? analysis.booking_status.payment}` : ""}
          </Row>
        )}
        {!!analysis.inferences?.length && <Row label="Inferred, not stated"><span className="italic text-[var(--haip-fg-subtle)]">{analysis.inferences.join(" · ")}</span></Row>}
      </div>
    </div>
  );
}
