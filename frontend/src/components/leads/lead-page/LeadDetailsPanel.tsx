"use client";
// Lead details: a side panel from 1200px (hideable), a full-screen sheet that slides up below that. Header (name,
// masked phone, source, owner, stage, temperature), actions, the ONE next step with the AI summary, trip fields,
// tasks, quotes and bookings, contact and identity, and the small autopilot controls.
import { useState } from "react";
import { Calculator, Calendar, ChevronDown, Flag, MessageSquare, Phone, RefreshCw, Sparkles, X } from "@/lib/icons";
import { cn } from "@/lib/utils";
import { Card, CardBody, StatusPill } from "@/components/ui/kit";
import { AIRecommendationCard, type RecommendedAction } from "@/components/ai/AIRecommendationCard";
import { AutopilotPanel } from "@/components/leads/AutopilotPanel";
import type { NextStep, NextStepAction, Temperature } from "@/lib/leadNextStep";
import { AiAnalysis } from "./AiAnalysis";
import { JourneyCard } from "./JourneyCard";
import { WhereFromCard } from "./WhereFromCard";
import { LeadReviewCard } from "./LeadReviewCard";
import { TripFields } from "./TripFields";
import { AiRepliesToggle, ContactCard, DealsCard, TasksCard, useReveal } from "./PanelSections";
import { sourceName, istDate } from "./format";
import type { LeadDetail, LeadFeed, PipelineStage, RunAction } from "./types";

export interface LeadPerms { canCall: boolean; canSend: boolean; canQuote: boolean; canBook: boolean; canEdit: boolean; canReveal: boolean; canOpenBookings: boolean }

const ACTION_LABEL: Record<NextStepAction, string> = {
  call: "Call now", message: "Message", quote: "Send quote", book: "Add booking", open_booking: "Open booking", review_draft: "Review the AI reply", stage: "Move stage", mark_sold: "Mark as Sold",
};
const btn = "inline-flex min-h-11 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl px-3.5 text-[14px] font-semibold";
const btnPrimary = `${btn} bg-primary text-primary-foreground`;
const btnTint = `${btn} bg-[var(--haip-primary-tint)] text-primary`;
const btnOutline = `${btn} border border-[var(--haip-border-strong)] bg-[var(--haip-card)] text-[var(--haip-fg-2)]`;

/** Buttons for a next step, filtered to what this person may do. Shared by the panel and the pinned bar. */
export function stepButtons(step: NextStep, perms: LeadPerms): NextStepAction[] {
  return step.actions.filter(a => (a !== "call" || perms.canCall) && (a !== "message" || perms.canSend) && (a !== "quote" || perms.canQuote)
    && (a !== "book" || perms.canBook) && (a !== "open_booking" || perms.canOpenBookings) && (a !== "review_draft" || perms.canSend)
    && (a !== "stage" || perms.canEdit) && (a !== "mark_sold" || perms.canEdit));
}

export function StepButton({ action, primary, run, small }: { action: NextStepAction; primary?: boolean; run: RunAction; small?: boolean }) {
  return (
    <button type="button" onClick={() => run(action === "review_draft" ? "review_draft" : action)}
      className={cn(primary ? btnPrimary : btnOutline, small && "sm:min-h-9 sm:px-3 sm:text-[13px]")}>
      {action === "call" && <Phone size={14} aria-hidden />}{ACTION_LABEL[action]}
    </button>
  );
}

function SummaryBox({ lead, stageLabel, stages, onRefresh, refreshing }: {
  lead: LeadDetail; stageLabel: string; stages: PipelineStage[]; onRefresh: () => void; refreshing: boolean;
}) {
  const a = lead.ai_analysis;
  const writtenAt = a?.written_stage_key;
  const writtenLabel = stages.find(s => s.key === writtenAt)?.label ?? writtenAt;
  const current = stages.find(s => s.key === lead.stage_key);
  const stale = writtenAt ? writtenAt !== lead.stage_key
    : !!lead.ai_summary && !current?.is_closed_lost && /\b(marked|moved|closed)\b[^.]{0,20}\blost\b/i.test(lead.ai_summary);
  return (
    <div className="grid gap-1 rounded-xl bg-[var(--haip-primary-tint)] px-3 py-2.5 text-[14px]">
      <span className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 text-[12px] font-bold text-primary"><Sparkles size={12} aria-hidden /> AI summary</span>
        <button type="button" onClick={onRefresh} disabled={refreshing} aria-label="Refresh the AI summary"
          className="grid size-11 place-items-center rounded-lg text-primary disabled:opacity-60 sm:size-8"><RefreshCw size={13} className={refreshing ? "animate-spin" : ""} aria-hidden /></button>
      </span>
      <p className="text-[var(--haip-fg)]">{lead.ai_summary || "No summary yet. It is written in the background after the next message or call."}</p>
      {stale && (
        <p className="text-[12.5px] font-semibold text-[var(--haip-status-warning-fg)]" data-testid="summary-stale">
          {writtenAt ? `Written when the lead was ${writtenLabel}. ` : "This summary may be out of date. "}The stage is now {stageLabel}; the next step above follows the stage.
        </p>
      )}
    </div>
  );
}

export function LeadDetailsPanel({ lead, feed, stages, step, temp, perms, run, onClose, onRefresh, refreshing, meRole, onAddSignal }: {
  lead: LeadDetail; feed?: LeadFeed; stages: PipelineStage[]; step: NextStep | null; temp: Temperature; perms: LeadPerms; run: RunAction;
  onClose: () => void; onRefresh: () => void; refreshing: boolean; meRole: string; onAddSignal?: () => void;
}) {
  const [showAnalysis, setShowAnalysis] = useState(false);
  const reveal = useReveal(lead.inquiry_id);
  const stage = stages.find(s => s.key === lead.stage_key);
  const stageLabel = stage?.label ?? (lead.stage_key || lead.inquiry_stage || "").replace(/_/g, " ");
  const closed = !!stage?.is_closed_lost || lead.stage_key === "unsuitable";
  const buttons = step ? stepButtons(step, perms) : [];
  const c = feed?.contact;

  return (
    <div className="grid content-start gap-3.5">
      <div className="sticky top-0 z-[2] -mx-1 flex items-center justify-between gap-2 bg-[var(--haip-app-bg)] px-1 py-1.5">
        <h2 className="font-[family-name:var(--font-display)] text-[18px] font-semibold text-[var(--haip-fg)]">Lead details</h2>
        <button type="button" onClick={onClose} className="inline-flex min-h-11 items-center gap-1 rounded-xl border border-[var(--haip-border-strong)] px-3 text-[14px] font-semibold text-[var(--haip-fg-2)]">
          <X size={15} aria-hidden /> <span className="min-[1200px]:hidden">Close</span><span className="hidden min-[1200px]:inline">Hide</span>
        </button>
      </div>

      <Card>
        <CardBody className="grid gap-3 pt-4">
          <div className="flex min-w-0 items-start gap-3">
            <span aria-hidden className="grid size-[52px] shrink-0 place-items-center rounded-full bg-[var(--haip-primary-tint)] font-[family-name:var(--font-display)] text-[22px] font-bold text-primary">
              {(lead.display_name || "?").charAt(0).toUpperCase()}
            </span>
            <div className="grid min-w-0 gap-1">
              <h1 className="haip-page-title haip-page-title--keep break-words text-[24px] leading-tight">{lead.display_name}</h1>
              <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[13px] text-[var(--haip-fg-subtle)]">
                <span className="tabular-nums">{reveal.shown?.phone || c?.phone_masked || "No phone yet"}</span>
                {perms.canReveal && c?.has_phone && !reveal.shown && (
                  <button type="button" onClick={reveal.reveal} className="min-h-11 font-semibold text-primary sm:min-h-0">Show</button>
                )}
                <span>This lead: {sourceName(lead.source)}</span>
                {c?.first_touch_at && <span>First contact {istDate(c.first_touch_at)}</span>}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button type="button" onClick={() => run("stage")} disabled={!perms.canEdit} aria-haspopup="dialog"
              className="inline-flex min-h-11 items-center gap-1 rounded-full bg-[var(--haip-primary-tint)] px-3 text-[13px] font-semibold text-primary disabled:opacity-80 sm:min-h-9">
              <Flag size={13} aria-hidden /> {stageLabel || "No stage"} {perms.canEdit && <ChevronDown size={13} aria-hidden />}
            </button>
            <button type="button" onClick={() => run("owner")} disabled={!perms.canEdit} aria-haspopup="dialog"
              className="inline-flex min-h-11 items-center gap-1 rounded-full border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[13px] font-semibold text-[var(--haip-fg-2)] disabled:opacity-80 sm:min-h-9">
              {lead.assigned_agent_name || "Nobody owns this yet"} {perms.canEdit && <ChevronDown size={13} aria-hidden />}
            </button>
            <StatusPill tone={temp.tone}>{temp.label}</StatusPill>
          </div>
          <div className="flex flex-wrap gap-2">
            {perms.canCall && <button type="button" className={btnPrimary} onClick={() => run("call")}><Phone size={15} aria-hidden /> Call</button>}
            {perms.canSend && <button type="button" className={btnTint} onClick={() => run("message")}><MessageSquare size={15} aria-hidden /> WhatsApp</button>}
            {perms.canQuote && <button type="button" className={btnOutline} onClick={() => run("quote")}><Calculator size={15} aria-hidden /> Send quote</button>}
            {perms.canBook && <button type="button" className={btnOutline} onClick={() => run("book")}><Calendar size={15} aria-hidden /> Add booking</button>}
            {perms.canEdit && <button type="button" className={btnOutline} onClick={() => run("stage")}><Flag size={15} aria-hidden /> Move stage</button>}
            {perms.canEdit && !closed && !stage?.is_closed_won && (
              <button type="button" className={`${btn} text-[var(--haip-status-danger-fg)]`} onClick={() => run("lost")}>Mark lost</button>
            )}
          </div>
        </CardBody>
      </Card>

      <Card role="region" className="border-l-4 border-l-[var(--haip-accent)]" aria-label="Next step">
        <CardBody className="grid gap-2.5 pt-4">
          <span className="flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-wide text-[var(--haip-accent-ink)]"><Sparkles size={12} aria-hidden /> Next step</span>
          <h3 className="font-[family-name:var(--font-display)] text-[19px] font-semibold leading-tight text-[var(--haip-fg)]">{step ? step.title : "Working it out…"}</h3>
          {step && <p className="text-[14px] text-[var(--haip-fg-2)]">{step.why}</p>}
          {buttons.length > 0 && <div className="flex flex-wrap gap-2">{buttons.map((a, i) => <StepButton key={a} action={a} primary={i === 0} run={run} />)}</div>}
          <SummaryBox lead={lead} stageLabel={stageLabel} stages={stages} onRefresh={onRefresh} refreshing={refreshing} />
          <button type="button" onClick={() => setShowAnalysis(v => !v)} aria-expanded={showAnalysis}
            className="inline-flex min-h-11 items-center gap-1 justify-self-start text-[13px] font-semibold text-primary">
            Full analysis <ChevronDown size={13} className={cn("transition-transform", showAnalysis && "rotate-180")} aria-hidden />
          </button>
          {showAnalysis && <AiAnalysis analysis={lead.ai_analysis} onRefresh={onRefresh} refreshing={refreshing} />}
        </CardBody>
      </Card>

      <JourneyCard inquiryId={lead.inquiry_id} canEdit={perms.canEdit} />
      <LeadReviewCard inquiryId={lead.inquiry_id} leadType={lead.lead_type} validation={lead.validation} canEdit={perms.canEdit} />
      <WhereFromCard inquiryId={lead.inquiry_id} canEdit={perms.canEdit} />
      <TripFields lead={lead} feed={feed} canEdit={perms.canEdit} />
      <TasksCard feed={feed} inquiryId={lead.inquiry_id} closed={closed} run={run} />
      <DealsCard lead={lead} feed={feed} canQuote={perms.canQuote} canBook={perms.canBook} canOpenBookings={perms.canOpenBookings} run={run} />
      <ContactCard lead={lead} feed={feed} canReveal={perms.canReveal} reveal={reveal} onAddSignal={onAddSignal} />

      <Card>
        <CardBody className="grid gap-2 pt-3">
          {feed && <AiRepliesToggle channels={feed.channels} inquiryId={lead.inquiry_id} />}
          <AutopilotPanel inquiryId={lead.inquiry_id} autopilot={lead.autopilot} canEdit={["owner", "manager", "reservations", "concierge"].includes(meRole)} />
          {(lead.recommended_actions ?? []).length > 0 && (
            <AIRecommendationCard title="Suggested stage change"
              summary={(lead.recommended_actions![0] as RecommendedAction & { reason?: string }).reason ?? "The autopilot suggests a change for this lead."}
              entityRefs={{ inquiry_id: lead.inquiry_id }} actions={lead.recommended_actions!} source="lead_detail"
              invalidateKeys={[["lead", lead.inquiry_id], ["lead-feed", lead.inquiry_id]]} />
          )}
        </CardBody>
      </Card>
    </div>
  );
}
