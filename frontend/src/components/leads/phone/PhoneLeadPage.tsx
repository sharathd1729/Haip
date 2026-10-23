"use client";
// The lead page on a phone (mobile-first plan phase 7, approved mockup "A lead"): who and what they want at the top, the three
// actions as big buttons (Call, WhatsApp, Send package), the AI note on one line with "more", then tabs:
//   Activity  the conversation (calls, quotes, bookings, stage changes inline; GET /leads/{id}/feed) and the composer
//   Trip      trip fields, the valid-lead review, where they came from, the won / lost reason on a closed lead
//   Quotes    quotes and bookings (DealsCard), tasks
//   Evidence  chat exports and recordings (EvidenceCard)
// Everything is the desktop page's own pieces and endpoints (components/leads/lead-page/*): stage, owner, lost-with-reason,
// won-with-reason, task, log call, send package and the call panel are the same sheets. Desktop keeps its own layout.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { Calendar, CheckSquare, ChevronLeft, Eye, Flag, MessageCircle, MoreHorizontal, Phone, Send, Sparkles, User } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { EmptyState, OneLineSummary, SheetActions, Tabs, sheetActionCls } from "@/components/ui/kit";
import { useQuoteSheet } from "@/components/quotes/QuoteSheetProvider";
import { useCanQuote } from "@/components/quotes/SendQuoteButton";
import { SalesActionCard } from "@/components/sales/SalesActionCard";
import { BOOKING_READ_ROLES, canSendMessages } from "@/lib/permissions";
import { deriveNextStep, pickLiveBooking } from "@/lib/leadNextStep";
import { LeadThread } from "@/components/leads/lead-page/LeadThread";
import { LeadComposer, type ComposerHandle } from "@/components/leads/lead-page/LeadComposer";
import { CallPanel, useClickToCall } from "@/components/leads/lead-page/CallPanel";
import { LogCallSheet } from "@/components/leads/lead-page/LogCallSheet";
import { LostSheet, MoreSheet, OwnerSheet, StageSheet, TaskSheet, type SheetKey } from "@/components/leads/lead-page/LeadSheets";
import { OutcomeSheet } from "@/components/leads/lead-page/OutcomeSheet";
import { SendPackageSheet } from "@/components/leads/lead-page/SendPackageSheet";
import { TripFields } from "@/components/leads/lead-page/TripFields";
import { LeadReviewCard } from "@/components/leads/lead-page/LeadReviewCard";
import { WhereFromCard } from "@/components/leads/lead-page/WhereFromCard";
import { EvidenceCard } from "@/components/leads/lead-page/EvidenceCard";
import { DealsCard, TasksCard, useReveal } from "@/components/leads/lead-page/PanelSections";
import { firstName } from "@/components/leads/lead-page/format";
import type { LeadActionKey, LeadDetail, LeadFeed, PipelineStage } from "@/components/leads/lead-page/types";
import { LeadHero, OutcomeReasonCard } from "./LeadHero";

type Tab = "activity" | "trip" | "quotes" | "evidence";
const LIVE_QUOTE = new Set(["issued", "pending_approval", "accepted"]);
const status = (e: unknown) => (e as { response?: { status?: number } })?.response?.status;

export function PhoneLeadPage({ inquiryId }: { inquiryId: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const user = session?.user as { role?: string; id?: string } | undefined;
  const role = user?.role ?? "";
  const quoteSheet = useQuoteSheet();
  const canQuote = useCanQuote();
  const [tab, setTab] = useState<Tab>("activity");
  const [sheet, setSheet] = useState<SheetKey>(null);
  const [wonStage, setWonStage] = useState<PipelineStage | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const [packageOpen, setPackageOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const composer = useRef<ComposerHandle>(null);
  useEffect(() => setMounted(true), []);

  // Same queries and keys as the desktop page, so switching layout or coming back reuses the cache.
  const leadQ = useQuery<LeadDetail>({
    queryKey: ["lead", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}`).then(r => r.data),
    refetchOnWindowFocus: true, staleTime: 10_000, retry: (n, e) => n < 2 && ![401, 403, 404].includes(status(e) ?? 0),
  });
  const feedQ = useQuery<LeadFeed>({
    queryKey: ["lead-feed", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}/feed`).then(r => r.data),
    refetchOnWindowFocus: true, staleTime: 10_000, enabled: leadQ.isSuccess,
  });
  const viewedFor = useRef<string | null>(null);
  useEffect(() => {   // lead journey "viewed", once per visit, best-effort (as on desktop)
    if (!leadQ.isSuccess || viewedFor.current === inquiryId) return;
    viewedFor.current = inquiryId;
    try { void Promise.resolve(api.post(`/leads/${inquiryId}/viewed`)).catch(() => undefined); } catch { /* tracking only */ }
  }, [leadQ.isSuccess, inquiryId]);
  const stagesQ = useQuery<PipelineStage[]>({ queryKey: ["pipeline-stages"], queryFn: () => api.get("/pipeline-stages").then(r => r.data), staleTime: 5 * 60_000 });
  const { data: me } = useQuery<{ id: string }>({ queryKey: ["users", "me"], queryFn: () => api.get("/users/me").then(r => r.data), staleTime: 60_000 });
  const refresh = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/refresh-summary`),
    onSuccess: () => { toast({ title: "Summary queued", description: "It is rewritten in the background." }); setTimeout(() => qc.invalidateQueries({ queryKey: ["lead", inquiryId] }), 8000); },
  });

  const lead = leadQ.data;
  const feed = feedQ.data;
  const stages = stagesQ.data ?? [];
  const items = useMemo(() => feed?.items ?? [], [feed]);
  const calls = useMemo(() => items.filter(i => i.kind === "call"), [items]);
  const refetchFeed = useCallback(() => { feedQ.refetch(); }, [feedQ]);
  const call = useClickToCall(inquiryId, calls, refetchFeed);
  const reveal = useReveal(inquiryId);

  const name = firstName(lead?.display_name);
  const hasPhone = !!feed?.contact.has_phone;
  const canCall = hasPhone && !["read_only", "compliance", "marketing"].includes(role);
  const canSend = canSendMessages(role);
  const canBook = ["owner", "manager", "reservations"].includes(role);
  const canEdit = ["owner", "manager", "reservations", "concierge"].includes(role);
  const canReveal = ["owner", "manager", "reservations", "concierge", "compliance"].includes(role);
  const canOpenBookings = (BOOKING_READ_ROLES as string[]).includes(role);
  const stage = stages.find(s => s.key === lead?.stage_key);
  const stageLabel = stage?.label ?? (lead?.stage_key || lead?.inquiry_stage || "").replace(/_/g, " ");   // same fallback as the details panel
  const quote = (lead?.quote_history ?? []).find(q => (q.option_rank ?? 1) === 1 && LIVE_QUOTE.has(q.status || ""));
  const booking = pickLiveBooking(feed?.bookings ?? [], inquiryId, lead?.check_in);
  const step = feed && lead ? deriveNextStep({
    name, stage: { key: lead.stage_key, label: stage?.label, category: stage?.category, is_closed_won: stage?.is_closed_won, is_closed_lost: stage?.is_closed_lost },
    hasPhone, lastInboundAt: feed.facts.last_inbound_at, lastOutboundAt: feed.facts.last_outbound_at,
    unansweredOutboundCalls: feed.facts.unanswered_outbound_calls, missedInboundUnreturned: feed.facts.missed_inbound_unreturned,
    pendingDrafts: feed.facts.pending_drafts, lostReason: feed.trip.lost_reason,
    openQuote: quote ? { amount: quote.amount, validUntil: quote.valid_until, sharedVia: quote.shared_via, status: quote.status } : null,
    booking: booking ? { id: booking.booking_id, outstanding: booking.amount_restricted ? null : booking.outstanding, checkIn: booking.check_in,
      checkOut: booking.check_out, propertyName: booking.property_name } : null,
    pastBooking: (feed.bookings ?? []).some(b => b.inquiry_id === inquiryId && b.status === "checked_out"),
  }) : null;

  const message = () => { setTab("activity"); setTimeout(() => composer.current?.focus(), 250); };
  const run = (key: LeadActionKey) => {
    switch (key) {
      case "call":
        if (!hasPhone) { toast({ variant: "error", title: `${name} hasn't shared a phone number yet` }); return; }
        setSheet(null); call.start(); return;
      case "message": setSheet(null); message(); return;
      case "quote": setSheet(null); quoteSheet.open({ inquiryId, from: "lead", name: lead?.display_name }); return;
      case "book": router.push(`/dashboard/bookings/new?inquiry=${encodeURIComponent(inquiryId)}`); return;
      case "open_booking": if (booking) router.push(`/dashboard/bookings/${booking.booking_id}`); return;
      case "mark_sold": {
        const won = stages.find(st => st.is_closed_won);
        if (!won) { toast({ variant: "error", title: "This workspace has no Sold stage", description: "Add one in Leads → Pipeline settings." }); return; }
        setWonStage(won); setSheet("won"); return;
      }
      case "review_draft":
        setTab("activity");
        setTimeout(() => document.querySelector("[data-testid='thread-draft']")?.scrollIntoView({ block: "center", behavior: "smooth" }), 250);
        return;
      default: setSheet(key as SheetKey);
    }
  };

  if (leadQ.isPending) {
    return <div className="grid gap-3 px-4 py-3" aria-busy="true"><Skeleton className="h-20 rounded-2xl" /><Skeleton className="h-14 rounded-xl" /><Skeleton className="h-64 rounded-2xl" /></div>;
  }
  if (leadQ.isError || !lead) {
    const s = status(leadQ.error);
    const [title, hint] = s === 404 ? ["Lead not found", "It may have been merged into another lead, or it belongs to someone else's list."]
      : s === 403 ? ["You don't have access to this lead", "Ask an owner or manager to give your role access to leads."]
        : s === 401 ? ["You've been signed out", "Sign in again to open this lead."]
          : ["Couldn't load this lead", "Check your connection and try again."];
    return (
      <EmptyState title={title} hint={hint} action={<div className="flex gap-2">
        {s !== 404 && s !== 403 && s !== 401 && <button type="button" onClick={() => leadQ.refetch()} className="haip-btn-primary min-h-11">Try again</button>}
        <Link href="/dashboard/leads" className="haip-btn-secondary inline-flex min-h-11 items-center">Back to Leads</Link>
      </div>} />
    );
  }

  const closedKind = stage?.is_closed_won ? "won" : stage?.is_closed_lost ? "lost" : null;
  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="grid gap-3 px-4 pb-8 pt-2">
        <div className="flex items-center justify-between">
          <Link href="/dashboard/leads" aria-label="Back to Leads" className="-ml-2 grid size-11 place-items-center rounded-xl text-primary"><ChevronLeft size={20} aria-hidden /></Link>
          <button type="button" onClick={() => setSheet("more")} aria-label="More actions" aria-haspopup="dialog" className="-mr-2 grid size-11 place-items-center rounded-xl text-[var(--haip-fg-2)]"><MoreHorizontal size={20} aria-hidden /></button>
        </div>

        <section className="haip-card grid gap-3 px-3.5 py-3">
          <LeadHero lead={lead} feed={feed} stageLabel={stageLabel} canEdit={canEdit} onStage={() => setSheet("stage")} onOwner={() => setSheet("owner")} />
          <SheetActions>
            {canCall && <button type="button" className={sheetActionCls(true)} onClick={() => run("call")}><Phone size={19} aria-hidden />Call</button>}
            {canSend && <button type="button" className={sheetActionCls(!canCall)} onClick={message}><MessageCircle size={19} aria-hidden />WhatsApp</button>}
            {canSend && hasPhone && <button type="button" className={sheetActionCls()} onClick={() => setPackageOpen(true)}><Send size={19} aria-hidden />Send package</button>}
          </SheetActions>
        </section>

        <section aria-label="AI note" className="grid gap-1 rounded-xl bg-[var(--haip-olive-bg)] px-3 py-2.5 text-[var(--haip-olive-fg)]">
          <span className="flex items-center justify-between gap-2 text-[12px] font-bold">
            AI note
            <button type="button" onClick={() => refresh.mutate()} disabled={refresh.isPending} className="min-h-11 px-1 text-[12.5px] font-semibold text-primary disabled:opacity-60">
              {refresh.isPending ? "Asking…" : "Refresh"}
            </button>
          </span>
          {lead.ai_summary ? <OneLineSummary text={lead.ai_summary} className="text-[var(--haip-olive-fg)]" /> : <span className="text-[13px] opacity-80">No AI note yet.</span>}
          {step && <span className="flex items-start gap-1.5 text-[13px]"><Sparkles size={13} className="mt-0.5 shrink-0" aria-hidden /><span><strong>Next:</strong> {step.title}</span></span>}
        </section>

        <Tabs label="Lead sections" value={tab} onChange={v => setTab(v as Tab)} className="w-full [&>button]:flex-1 [&>button]:justify-center [&>button]:px-2"
          items={[{ value: "activity", label: "Activity" }, { value: "trip", label: "Trip" }, { value: "quotes", label: "Quotes", count: lead.quote_history?.length || undefined },
            { value: "evidence", label: "Evidence" }]} />

        {tab === "activity" && (
          <div className="grid gap-2">
            {feedQ.isPending ? <div className="grid gap-2"><Skeleton className="h-12 w-2/3 rounded-2xl" /><Skeleton className="ml-auto h-12 w-1/2 rounded-2xl" /></div>
              : feedQ.isError ? <EmptyState title="Couldn't load the conversation" hint="Check your connection and try again."
                action={<button type="button" onClick={() => feedQ.refetch()} className="haip-btn-primary min-h-11">Try again</button>} />
                : <LeadThread items={items} inquiryId={inquiryId} canSend={canSend} canOpenBookings={canOpenBookings} capped={!!feed?.capped} messagesRestricted={!!feed?.messages_restricted} />}
            <SalesActionCard inquiryId={inquiryId} />
            <LeadComposer ref={composer} channels={feed?.channels ?? []} name={name} canSend={canSend} canQuote={canQuote} canBook={canBook} hasPhone={canCall} run={run}
              onSent={ch => { toast({ variant: "success", title: `Sent on ${ch === "instagram" ? "Instagram" : "WhatsApp"}`, description: "Logged on this lead." }); qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] }); }}
              onError={msg => toast({ variant: "error", title: "Not sent", description: msg })} />
          </div>
        )}
        {tab === "trip" && (
          <div className="grid gap-3">
            {closedKind && <OutcomeReasonCard inquiryId={inquiryId} kind={closedKind} />}
            <TripFields lead={lead} feed={feed} canEdit={canEdit} />
            <LeadReviewCard inquiryId={inquiryId} leadType={lead.lead_type} validation={lead.validation} validity={lead.validity} canEdit={canEdit} />
            <WhereFromCard inquiryId={inquiryId} canEdit={canEdit} />
          </div>
        )}
        {tab === "quotes" && (
          <div className="grid gap-3">
            <DealsCard lead={lead} feed={feed} canQuote={canQuote} canBook={canBook} canOpenBookings={canOpenBookings} run={run} />
            <TasksCard feed={feed} inquiryId={inquiryId} closed={!!stage?.is_closed_lost || lead.stage_key === "unsuitable"} run={run} />
          </div>
        )}
        {tab === "evidence" && <EvidenceCard inquiryId={inquiryId} canEdit={canEdit} />}
      </div>

      {mounted && createPortal(
        <CallPanel phase={call.phase} error={call.error} newCall={call.newCall} name={name} onClose={call.close}
          onRetry={() => { call.close(); setTimeout(call.start, 0); }}
          onLogCall={canEdit ? () => { call.close(); setLogOpen(true); } : undefined}
          onSendPackage={canSend && hasPhone ? () => { call.close(); setPackageOpen(true); } : undefined} />, document.body)}
      <LogCallSheet open={logOpen} onClose={() => setLogOpen(false)} inquiryId={inquiryId} name={name} />
      <SendPackageSheet open={packageOpen} onClose={() => setPackageOpen(false)} inquiryId={inquiryId} name={name} />
      <StageSheet open={sheet === "stage"} onClose={() => setSheet(null)} inquiryId={inquiryId} stages={stages} currentKey={lead.stage_key}
        canReverse={["owner", "manager"].includes(role)} onLost={() => setSheet("lost")} onWon={s => { setWonStage(s); setSheet("won"); }} />
      <OutcomeSheet open={sheet === "won"} onClose={() => setSheet(null)} inquiryId={inquiryId} name={name} kind="won" stage={wonStage ?? stages.find(s => s.is_closed_won)} />
      <LostSheet open={sheet === "lost"} onClose={() => setSheet(null)} inquiryId={inquiryId} name={name} lostStage={stages.find(s => s.is_closed_lost)} />
      <OwnerSheet open={sheet === "owner"} onClose={() => setSheet(null)} inquiryId={inquiryId} ownerId={lead.assigned_agent_id} />
      <TaskSheet open={sheet === "task"} onClose={() => setSheet(null)} inquiryId={inquiryId} guestId={lead.guest_id} meId={me?.id ?? user?.id} name={name} />
      <MoreSheet open={sheet === "more"} onClose={() => setSheet(null)} items={[
        ...(canQuote ? [{ key: "quote" as const, label: "Send quote", icon: <Sparkles size={15} aria-hidden />, onClick: () => run("quote") }] : []),
        ...(canBook ? [{ key: "book" as const, label: "Add booking", icon: <Calendar size={15} aria-hidden />, onClick: () => run("book") }] : []),
        ...(canEdit ? [{ key: "stage" as const, label: "Move stage", hint: `Now: ${stageLabel}`, icon: <Flag size={15} aria-hidden />, onClick: () => setSheet("stage") }] : []),
        ...(canEdit && !closedKind ? [{ key: "lost" as const, label: "Mark lost", onClick: () => setSheet("lost") }] : []),
        ...(canEdit ? [{ key: "log_call" as const, label: "Log a call", hint: "A call from your own phone", icon: <Phone size={15} aria-hidden />, onClick: () => { setSheet(null); setLogOpen(true); } }] : []),
        { key: "task" as const, label: "Add a task", icon: <CheckSquare size={15} aria-hidden />, onClick: () => setSheet("task") },
        ...(canEdit ? [{ key: "owner" as const, label: "Change owner", hint: `Now: ${lead.assigned_agent_name || "nobody"}`, icon: <User size={15} aria-hidden />, onClick: () => setSheet("owner") }] : []),
        ...(canReveal && hasPhone ? [{ key: "reveal" as const, label: reveal.shown?.phone ? `Phone: ${reveal.shown.phone}` : "Show full phone number", hint: "Shown for 30 seconds · logged", icon: <Eye size={15} aria-hidden />, onClick: () => { reveal.reveal(); } }] : []),
      ]} />
    </div>
  );
}
