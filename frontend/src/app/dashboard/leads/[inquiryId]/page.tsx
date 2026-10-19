"use client";
// Lead page, layout "C · Chat" (approved Oct 2026, mock-up variation C). The conversation reads like WhatsApp, with
// calls, quotes, bookings, stage changes, tasks and merges inline (GET /leads/{id}/feed). A pinned "Next step" bar
// (lib/leadNextStep.ts, the ONE place the next step is worked out), a one-line trip summary that opens the details,
// and a composer at the bottom. Details: side panel from 1200px (hideable), full-screen sheet below that.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Calculator, Calendar, CheckSquare, ChevronDown, ChevronLeft, Eye, Flag, LayoutGrid, Phone, Sparkles, User } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/page";
import { useToast } from "@/components/ui/toast";
import { useQuoteSheet } from "@/components/quotes/QuoteSheetProvider";
import { useCanQuote } from "@/components/quotes/SendQuoteButton";
import { BOOKING_READ_ROLES, canSendMessages } from "@/lib/permissions";
import { deriveNextStep, leadTemperature, pickLiveBooking } from "@/lib/leadNextStep";
import { LeadThread } from "@/components/leads/lead-page/LeadThread";
import { LeadComposer, type ComposerHandle } from "@/components/leads/lead-page/LeadComposer";
import { CallPanel, useClickToCall } from "@/components/leads/lead-page/CallPanel";
import { LeadDetailsPanel, StepButton, stepButtons, type LeadPerms } from "@/components/leads/lead-page/LeadDetailsPanel";
import { LostSheet, MoreSheet, OwnerSheet, StageSheet, TaskSheet, type SheetKey } from "@/components/leads/lead-page/LeadSheets";
import { useReveal } from "@/components/leads/lead-page/PanelSections";
import { SalesActionCard } from "@/components/sales/SalesActionCard";
import { SignalDrawer } from "@/components/leads/SignalDrawer";
import { firstName, inr, istDate, nights } from "@/components/leads/lead-page/format";
import type { LeadActionKey, LeadDetail, LeadFeed, PipelineStage } from "@/components/leads/lead-page/types";

const WIDE = "(min-width: 1200px)";
const LIVE_QUOTE = new Set(["issued", "pending_approval", "accepted"]);

function useWide(): boolean {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const m = window.matchMedia(WIDE);
    setWide(m.matches);
    const on = () => setWide(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return wide;
}

function status(e: unknown): number | undefined {
  return (e as { response?: { status?: number } })?.response?.status;
}

export default function LeadDetailPage() {
  const { inquiryId } = useParams<{ inquiryId: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const user = session?.user as { role?: string; id?: string } | undefined;
  const role = user?.role ?? "";
  const quoteSheet = useQuoteSheet();
  const canQuote = useCanQuote();
  const wide = useWide();
  const [panelOpen, setPanelOpen] = useState(false);
  const [sheet, setSheet] = useState<SheetKey>(null);
  const [signalOpen, setSignalOpen] = useState(false);
  const composer = useRef<ComposerHandle>(null);
  const threadEnd = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => { setPanelOpen(wide); }, [wide]);

  const leadQ = useQuery<LeadDetail>({
    queryKey: ["lead", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}`).then(r => r.data),
    refetchOnWindowFocus: true, staleTime: 10_000, retry: (n, e) => n < 2 && ![401, 403, 404].includes(status(e) ?? 0),
  });
  const feedQ = useQuery<LeadFeed>({
    queryKey: ["lead-feed", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}/feed`).then(r => r.data),
    refetchOnWindowFocus: true, staleTime: 10_000, enabled: leadQ.isSuccess,
  });
  const stagesQ = useQuery<PipelineStage[]>({ queryKey: ["pipeline-stages"], queryFn: () => api.get("/pipeline-stages").then(r => r.data), staleTime: 5 * 60_000 });
  const { data: me } = useQuery<{ id: string }>({ queryKey: ["users", "me"], queryFn: () => api.get("/users/me").then(r => r.data), staleTime: 60_000 });
  const refresh = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/refresh-summary`),
    onSuccess: () => { toast({ title: "Summary queued", description: "It is rewritten in the background." }); setTimeout(() => qc.invalidateQueries({ queryKey: ["lead", inquiryId] }), 8000); },
  });

  // "Mark Sold" from the next step: the same audited stage move as the stage menu (PATCH /inquiries/{id} {stage_id}).
  const markSold = useMutation({
    mutationFn: (stageId: string) => api.patch(`/inquiries/${inquiryId}`, { stage_id: stageId }),
    onSuccess: () => {
      toast({ variant: "success", title: "Marked Sold · logged" });
      qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
      qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] });
      qc.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Not changed", description: typeof d === "string" ? d : "Please try again." });
    },
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
  const perms: LeadPerms = {
    canCall: hasPhone && !["read_only", "compliance", "marketing"].includes(role),
    canSend: canSendMessages(role), canQuote, canBook: ["owner", "manager", "reservations"].includes(role),
    canEdit: ["owner", "manager", "reservations", "concierge"].includes(role),
    canReveal: ["owner", "manager", "reservations", "concierge", "compliance"].includes(role),
    canOpenBookings: (BOOKING_READ_ROLES as string[]).includes(role),
  };
  const stage = stages.find(s => s.key === lead?.stage_key);
  const quote = (lead?.quote_history ?? []).find(q => (q.option_rank ?? 1) === 1 && LIVE_QUOTE.has(q.status || ""));
  const booking = pickLiveBooking(feed?.bookings ?? [], inquiryId, lead?.check_in);
  const pastBooking = (feed?.bookings ?? []).some(b => b.inquiry_id === inquiryId && b.status === "checked_out");
  const facts = {
    name, stage: { key: lead?.stage_key, label: stage?.label, category: stage?.category, is_closed_won: stage?.is_closed_won, is_closed_lost: stage?.is_closed_lost },
    hasPhone, lastInboundAt: feed?.facts.last_inbound_at, lastOutboundAt: feed?.facts.last_outbound_at,
    unansweredOutboundCalls: feed?.facts.unanswered_outbound_calls, missedInboundUnreturned: feed?.facts.missed_inbound_unreturned,
    pendingDrafts: feed?.facts.pending_drafts, lostReason: feed?.trip.lost_reason,
    openQuote: quote ? { amount: quote.amount, validUntil: quote.valid_until, sharedVia: quote.shared_via, status: quote.status } : null,
    booking: booking ? { id: booking.booking_id, outstanding: booking.amount_restricted ? null : booking.outstanding, checkIn: booking.check_in,
      checkOut: booking.check_out, propertyName: booking.property_name } : null,
    pastBooking,
  };
  // Until the thread is in, the facts are unknown: show no step rather than a wrong one.
  const step = feed ? deriveNextStep(facts) : null;
  const temp = leadTemperature(facts);

  // Open on the newest message, like a chat; follow new items as they arrive.
  useEffect(() => { threadEnd.current?.scrollIntoView({ block: "end" }); }, [items.length]);
  useEffect(() => {
    if (!panelOpen || wide) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !sheet) setPanelOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panelOpen, wide, sheet]);

  const run = (key: LeadActionKey) => {
    const closeSheetOnPhone = () => { if (!wide) setPanelOpen(false); };
    switch (key) {
      case "call":
        if (!hasPhone) { toast({ variant: "error", title: `${name} hasn't shared a phone number yet` }); return; }
        closeSheetOnPhone(); setSheet(null); call.start(); return;
      case "message": closeSheetOnPhone(); setSheet(null); setTimeout(() => composer.current?.focus(), 250); return;
      case "quote": setSheet(null); quoteSheet.open({ inquiryId, from: "lead", name: lead?.display_name }); return;
      case "book": router.push(`/dashboard/bookings/new?inquiry=${encodeURIComponent(inquiryId)}`); return;
      case "open_booking": if (booking) router.push(`/dashboard/bookings/${booking.booking_id}`); return;
      case "mark_sold": {
        const won = stages.find(st => st.is_closed_won);
        if (!won) { toast({ variant: "error", title: "This workspace has no Sold stage", description: "Add one in Leads → Pipeline settings." }); return; }
        markSold.mutate(won.id);
        return;
      }
      case "review_draft":
        closeSheetOnPhone();
        setTimeout(() => document.querySelector("[data-testid='thread-draft']")?.scrollIntoView({ block: "center", behavior: "smooth" }), 250);
        return;
      default: setSheet(key as SheetKey);
    }
  };

  if (leadQ.isPending) {
    return (
      <div className="mx-auto grid w-full max-w-3xl gap-3 p-4">
        <Skeleton className="h-16 w-full rounded-2xl" /><Skeleton className="h-12 w-full rounded-xl" /><Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }
  if (leadQ.isError || !lead) {
    const s = status(leadQ.error);
    const [title, hint] = s === 404 ? ["Lead not found", "It may have been merged into another lead, or it belongs to someone else's list."]
      : s === 403 ? ["You don't have access to this lead", "Ask an owner or manager to give your role access to leads."]
        : s === 401 ? ["You've been signed out", "Sign in again to open this lead."]
          : ["Couldn't load this lead", "Check your connection and try again."];
    return (
      <EmptyState title={title} hint={hint} action={
        <div className="flex gap-2">
          {s !== 404 && s !== 403 && s !== 401 && <button type="button" onClick={() => leadQ.refetch()} className="min-h-11 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>}
          <Link href="/dashboard/leads" className="inline-flex min-h-11 items-center rounded-xl border border-[var(--haip-border-strong)] px-4 text-[14px] font-semibold text-[var(--haip-fg-2)]">Back to Leads</Link>
        </div>
      } />
    );
  }

  const stageLabel = stage?.label ?? (lead.stage_key || "").replace(/_/g, " ");
  const n = nights(lead.check_in, lead.check_out);
  const guests = (lead.adults ?? 0) + (lead.children ?? 0);
  const trip = [feed?.trip.route?.split(",")[0], lead.check_in && `${istDate(lead.check_in)}${n != null ? ` · ${n} night${n === 1 ? "" : "s"}` : ""}`,
    guests ? `${guests} guests` : null].filter(Boolean).join(" · ");
  const buttons = step ? stepButtons(step, perms).slice(0, 2) : [];

  const panel = (
    <LeadDetailsPanel lead={lead} feed={feed} stages={stages} step={step} temp={temp} perms={perms} run={run} meRole={role}
      onClose={() => setPanelOpen(false)} onRefresh={() => refresh.mutate()} refreshing={refresh.isPending}
      onAddSignal={["owner", "manager", "reservations"].includes(role) ? () => setSignalOpen(true) : undefined} />
  );

  return (
    // Phones: the chat column is exactly the screen between the 52px app header and the 60px bottom bar (plus the notch and
    // home-indicator insets), so the thread scrolls inside it and the composer sits just above the bottom bar.
    <div className="flex h-[calc(100dvh_-_7rem_-_env(safe-area-inset-top)_-_env(safe-area-inset-bottom))] min-h-0 overflow-hidden md:h-full">
      <div className="mx-auto flex min-h-0 w-full min-w-0 max-w-[860px] flex-1 flex-col overflow-x-hidden px-4">
        <header className="flex shrink-0 items-center gap-2 py-2">
          <Link href="/dashboard/leads" aria-label="Back to Leads" className="-ml-2 grid size-11 shrink-0 place-items-center rounded-xl text-primary hover:bg-[var(--haip-surface)]"><ChevronLeft size={20} aria-hidden /></Link>
          <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-full bg-[var(--haip-primary-tint)] font-[family-name:var(--font-display)] text-[17px] font-bold text-primary">{(lead.display_name || "?").charAt(0).toUpperCase()}</span>
          <div className="grid min-w-0 flex-1">
            <strong className="truncate font-[family-name:var(--font-display)] text-[16px] text-[var(--haip-fg)]">{lead.display_name}</strong>
            <span className="truncate text-[12.5px] text-[var(--haip-fg-subtle)]">{stageLabel} · {lead.assigned_agent_name || "No owner"}{feed?.contact.phone_masked ? ` · ${reveal.shown?.phone || feed.contact.phone_masked}` : ""}</span>
          </div>
          {perms.canCall && <button type="button" onClick={() => run("call")} className="hidden min-h-11 items-center gap-1.5 rounded-xl bg-primary px-3.5 text-[14px] font-semibold text-primary-foreground md:inline-flex"><Phone size={15} aria-hidden /> Call</button>}
          {perms.canQuote && <button type="button" onClick={() => run("quote")} className="hidden min-h-11 items-center gap-1.5 rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3.5 text-[14px] font-semibold text-[var(--haip-fg-2)] md:inline-flex"><Calculator size={15} aria-hidden /> Quote</button>}
          <button type="button" onClick={() => setPanelOpen(v => !v)} aria-expanded={panelOpen} aria-label={`${panelOpen ? "Hide" : "Show"} lead details`}
            className="grid size-11 shrink-0 place-items-center rounded-xl text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]"><LayoutGrid size={19} aria-hidden /></button>
        </header>

        <button type="button" onClick={() => setPanelOpen(true)} className="flex min-h-11 shrink-0 items-center justify-between gap-2 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 py-2 text-left text-[13.5px] text-[var(--haip-fg-2)] min-[1200px]:hidden">
          <span className="min-w-0 truncate">{trip || "No trip details yet"}{quote ? <> · <strong className="tabular-nums">{inr(quote.amount)}</strong> quoted</> : null}</span>
          <ChevronDown size={14} className="shrink-0" aria-hidden />
        </button>

        {step ? (
          <div data-testid="next-step-bar" className={cn("mt-2 flex shrink-0 items-start gap-2.5 rounded-xl px-3 py-2.5 text-[14px]",
            step.tone === "urgent" ? "bg-[var(--haip-accent-light)]" : "border border-[var(--haip-border)] bg-[var(--haip-surface)]")}>
            <Sparkles size={15} className="mt-0.5 shrink-0 text-[var(--haip-accent-ink)]" aria-hidden />
            <div className="grid min-w-0 flex-1 gap-1.5">
              <span><strong className="text-[var(--haip-accent-ink)]">Next:</strong> <span className="text-[var(--haip-fg)]">{step.title}</span></span>
              {buttons.length > 0 && <div className="flex flex-wrap gap-2">{buttons.map((a, i) => <StepButton key={a} action={a} primary={i === 0} run={run} small />)}</div>}
            </div>
          </div>
        ) : feedQ.isError ? null : <Skeleton className="mt-2 h-12 w-full shrink-0 rounded-xl" />}

        <div className="mt-2 min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain" data-testid="thread-scroll">
          {feedQ.isPending ? (
            <div className="grid gap-2 py-2"><Skeleton className="h-12 w-2/3 rounded-2xl" /><Skeleton className="ml-auto h-12 w-1/2 rounded-2xl" /><Skeleton className="h-24 w-full rounded-2xl" /></div>
          ) : feedQ.isError ? (
            <EmptyState title="Couldn't load the conversation" hint="Check your connection and try again."
              action={<button type="button" onClick={() => feedQ.refetch()} className="min-h-11 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>} />
          ) : (
            <LeadThread items={items} inquiryId={inquiryId} canSend={perms.canSend} canOpenBookings={perms.canOpenBookings}
              capped={!!feed?.capped} messagesRestricted={!!feed?.messages_restricted} />
          )}
          {/* A quote the AI sales agent prepared, waiting for a person: the last thing in the conversation. */}
          <SalesActionCard inquiryId={inquiryId} />
          <div ref={threadEnd} />
        </div>

        <LeadComposer ref={composer} channels={feed?.channels ?? []} name={name} canSend={perms.canSend} canQuote={perms.canQuote}
          canBook={perms.canBook} hasPhone={perms.canCall} run={run}
          onSent={ch => { toast({ variant: "success", title: `Sent on ${ch === "instagram" ? "Instagram" : "WhatsApp"}`, description: "Logged on this lead." }); qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] }); }}
          onError={msg => toast({ variant: "error", title: "Not sent", description: msg })} />
      </div>

      {wide ? (
        panelOpen && <aside aria-label="Lead details" className="w-[400px] shrink-0 overflow-y-auto border-l border-[var(--haip-border)] px-4 pb-6">{panel}</aside>
      ) : mounted && createPortal(
        <aside aria-label="Lead details" aria-hidden={!panelOpen} inert={!panelOpen || undefined}
          className={cn("fixed inset-0 z-50 overflow-y-auto overscroll-contain bg-[var(--haip-app-bg)] px-4 pb-[max(2.5rem,env(safe-area-inset-bottom))] pt-[env(safe-area-inset-top)] transition-transform duration-200 ease-out motion-reduce:transition-none",
            panelOpen ? "visible translate-y-0" : "invisible translate-y-full")}>
          {panel}
        </aside>, document.body)}

      {mounted && createPortal(
        <CallPanel phase={call.phase} error={call.error} newCall={call.newCall} name={name} onClose={call.close}
          onRetry={() => { call.close(); setTimeout(call.start, 0); }} onMessage={() => { call.close(); run("message"); }} />, document.body)}

      {signalOpen && (
        <SignalDrawer inquiryId={inquiryId} onClose={() => setSignalOpen(false)}
          onSuccess={() => { qc.invalidateQueries({ queryKey: ["lead", inquiryId] }); qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] }); }} />
      )}
      <StageSheet open={sheet === "stage"} onClose={() => setSheet(null)} inquiryId={inquiryId} stages={stages} currentKey={lead.stage_key}
        canReverse={["owner", "manager"].includes(role)} onLost={() => setSheet("lost")} />
      <LostSheet open={sheet === "lost"} onClose={() => setSheet(null)} inquiryId={inquiryId} name={name} lostStage={stages.find(s => s.is_closed_lost)} />
      <OwnerSheet open={sheet === "owner"} onClose={() => setSheet(null)} inquiryId={inquiryId} ownerId={lead.assigned_agent_id} />
      <TaskSheet open={sheet === "task"} onClose={() => setSheet(null)} inquiryId={inquiryId} guestId={lead.guest_id} meId={me?.id ?? user?.id} name={name} />
      <MoreSheet open={sheet === "more"} onClose={() => setSheet(null)} items={[
        ...(perms.canBook ? [{ key: "book" as const, label: "Add booking", icon: <Calendar size={15} aria-hidden />, onClick: () => run("book") }] : []),
        ...(perms.canEdit ? [{ key: "stage" as const, label: "Move stage", hint: `Now: ${stageLabel}`, icon: <Flag size={15} aria-hidden />, onClick: () => setSheet("stage") }] : []),
        ...(perms.canEdit && !stage?.is_closed_lost && !stage?.is_closed_won ? [{ key: "lost" as const, label: "Mark lost", onClick: () => setSheet("lost") }] : []),
        { key: "task" as const, label: "Add a task", icon: <CheckSquare size={15} aria-hidden />, onClick: () => setSheet("task") },
        ...(perms.canEdit ? [{ key: "owner" as const, label: "Change owner", hint: `Now: ${lead.assigned_agent_name || "nobody"}`, icon: <User size={15} aria-hidden />, onClick: () => setSheet("owner") }] : []),
        ...(perms.canReveal && hasPhone ? [{ key: "reveal" as const, label: "Show full phone number", hint: "Shown for 30 seconds · logged", icon: <Eye size={15} aria-hidden />, onClick: () => { setSheet(null); reveal.reveal(); } }] : []),
        { key: "more" as const, label: "Lead details", hint: "Trip, tasks, quotes, contact", onClick: () => { setSheet(null); setPanelOpen(true); } },
      ]} />
    </div>
  );
}
