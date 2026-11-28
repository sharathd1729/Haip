"use client";
// Leads on a phone (mobile-first plan, approved mockup 24 Oct 2026): search, one chip row (Needs action, then the workspace's
// own stages with their counts), Filters in a sheet, and compact rows (name · trip, the AI note on one line, stage / owner /
// waiting). Tapping a row opens its sheet: the full AI note, Call, Move stage, Assign and the full lead page. Stage and owner
// changes reuse the lead page's own sheets (PATCH /inquiries/{id}, the audited path; Lost asks for a reason). No board, bulk
// actions or column settings on the phone. Data: GET /leads?stage= (one stage at a time) and GET /leads/needs-action.
import { useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useSegment } from "@/lib/segments";
import { useSession } from "next-auth/react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ChevronDown, MessageCircle, Phone, SlidersHorizontal, UserPlus } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { GuestAvatar } from "@/components/crm/GuestAvatar";
import { CompactRow, EmptyState, Fab, FilterSearch, RowAction, RowList, RowTag } from "@/components/ui/kit";
import { usePipelineStages } from "@/hooks/usePipelineStages";
import type { LeadCard } from "@/components/leads/LeadCard";
import type { LeadsFilters } from "@/components/leads/LeadsFilterBar";
import { useDial } from "@/components/myday/useDial";
import { canRevealNumbers, useContactChoice } from "@/components/contact/ContactChoice";
import { LeadFiltersSheet, LeadRowSheet } from "./LeadRowSheet";
import { NewLeadAction } from "@/components/phone/QuickAdd";
import { HEAT_LABEL, HEAT_ROW, leadHeat, matches, tripText, waitedText, type Heat } from "./leadRow";

const AddLeadModal = dynamic(() => import("@/components/leads/AddLeadModal").then(m => m.AddLeadModal), { ssr: false });

const PAGE = 30;
const NEEDS_ACTION = "__needs_action__";
interface LeadsPage { total: number; page: number; page_size: number; stages: Record<string, { count: number }>; leads: LeadCard[] }
interface NeedsAction { buckets: { key: string; total: number; leads: LeadCard[] }[] }

function Row({ lead, stageLabel, heat, canReveal, onOpen }: { lead: LeadCard; stageLabel?: string; heat: Heat | null; canReveal: boolean; onOpen: () => void }) {
  const dial = useDial(lead.display_name);
  // Call = My phone | Office line (components/contact/ContactChoice)
  const callChoice = useContactChoice({ kind: "call", inquiryId: lead.inquiry_id, name: lead.display_name, canReveal,
    onOffice: () => dial.mutate({ inquiry_id: lead.inquiry_id }) });
  const hasPhone = lead.identity_signals?.includes("phone");
  const trip = tripText(lead);
  const waiting = lead.response_time_status === "waiting";
  const action = hasPhone
    ? <><RowAction icon={Phone} label={`Call ${lead.display_name}`} primary disabled={dial.isPending} onClick={callChoice.start} />{callChoice.sheet}</>
    : lead.pending_draft
      ? <RowAction icon={MessageCircle} label={`Review the AI reply to ${lead.display_name}`} href={`/dashboard/inbox?conversation=${lead.pending_draft.conversation_id}`} />
      : !lead.assigned_agent_id
        ? <RowAction icon={UserPlus} label={`Assign ${lead.display_name}`} onClick={onOpen} />
        : <RowAction icon={MessageCircle} label={`Open ${lead.display_name}`} href={`/dashboard/leads/${lead.inquiry_id}`} />;
  return (
    <CompactRow onClick={onOpen} label={`${lead.display_name}, open details`} avatar={<GuestAvatar name={lead.display_name} />}
      title={trip ? `${lead.display_name} · ${trip}` : lead.display_name}
      subtitle={lead.ai_summary || lead.ai_next_action || "No AI note yet"}
      className={heat ? HEAT_ROW[heat] : undefined}
      extra={<>
        {heat && <RowTag>{HEAT_LABEL[heat]}</RowTag>}
        {stageLabel && <RowTag tone="brand">{stageLabel}</RowTag>}
        {waiting && <RowTag tone={lead.sla_breached ? "danger" : "warning"}>waiting{waitedText(lead.response_time_seconds)}</RowTag>}
        {!lead.assigned_agent_id && <RowTag tone="warning">unassigned</RowTag>}
        {lead.pending_draft && <RowTag tone="info">AI draft</RowTag>}
      </>}
      actions={action} />
  );
}

export function PhoneLeads() {
  const booking = useSegment().booking.one;
  const { data: session } = useSession();
  const role = session?.user?.role;
  const { data: stages = [] } = usePipelineStages();
  const [chip, setChip] = useState(NEEDS_ACTION);
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<LeadsFilters>({});
  const [showFilters, setShowFilters] = useState(false);
  const [picked, setPicked] = useState<LeadCard | null>(null);
  const [adding, setAdding] = useState(false);
  const label = useMemo(() => Object.fromEntries(stages.map(s => [s.key, s.label])), [stages]);
  const nFilters = Object.values(filters).filter(Boolean).length;
  const onStage = chip !== NEEDS_ACTION;
  const nOn = nFilters + (onStage ? 1 : 0);          // the filter button's badge: a picked stage counts as one

  // Counts for every stage chip: any /leads answer carries the full per-stage summary for these filters.
  const meta = useQuery<LeadsPage>({
    queryKey: ["leads", "phone-meta", filters],
    queryFn: () => api.get("/leads", { params: { page: 1, page_size: 1, ...filters } }).then(r => r.data),
    staleTime: 30_000, refetchOnWindowFocus: true,
  });
  const needs = useQuery<NeedsAction>({
    queryKey: ["leads", "needs-action"],
    queryFn: () => api.get("/leads/needs-action").then(r => r.data),
    staleTime: 10_000, refetchInterval: 60_000, refetchOnWindowFocus: true,
  });
  const list = useInfiniteQuery<LeadsPage>({
    queryKey: ["leads", "stage", chip, filters],
    queryFn: ({ pageParam }) => api.get("/leads", { params: { page: pageParam, page_size: PAGE, stage: chip, ...filters } }).then(r => r.data),
    initialPageParam: 1,
    getNextPageParam: last => (last.page * last.page_size < last.total ? last.page + 1 : undefined),
    enabled: onStage, staleTime: 10_000, refetchInterval: 30_000, refetchOnWindowFocus: true,
  });

  const needsLeads = useMemo(() => {
    const seen = new Set<string>();
    return (needs.data?.buckets ?? []).flatMap(b => b.leads).filter(l => !seen.has(l.inquiry_id) && seen.add(l.inquiry_id));
  }, [needs.data]);
  const rows = (onStage ? list.data?.pages.flatMap(p => p.leads) ?? [] : needsLeads).filter(l => matches(l, q));
  const pending = onStage ? list.isPending : needs.isPending;
  const failed = onStage ? list.isError : needs.isError;
  const total = onStage ? list.data?.pages[0]?.total : needsLeads.length;

  const items = [
    { value: NEEDS_ACTION, label: "Needs action", count: needs.data ? (needs.data.buckets ?? []).reduce((s, b) => s + b.total, 0) : undefined },
    ...stages.map(s => ({ value: s.key, label: s.label, count: meta.data?.stages?.[s.key]?.count })),
  ];

  return (
    <div className="h-full overflow-y-auto bg-[var(--haip-bg,var(--background))]">
      <div className="grid gap-3 px-4 pb-24 pt-3">
        {/* "New lead" in words next to search: the floating "+" alone was missed on phones (owner feedback, Oct 2026). */}
        {/* ONE row on top (owner, 28 Nov 2026): the search bar is the header, with one filter button (its badge counts what is
            on) and one action. Stage and every other filter live in the sheet; no chip row. */}
        <div className="flex items-center gap-2">
          <FilterSearch value={q} onChange={setQ} placeholder={`Name or ${booking}`} label="Search leads" className="min-w-0 max-w-none" />
          <button type="button" onClick={() => setShowFilters(true)} aria-label={nOn ? `Filters, ${nOn} on` : "Filters"}
            className="relative flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg-2)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50">
            <SlidersHorizontal size={18} aria-hidden />
            {nOn > 0 && <span aria-hidden className="absolute -right-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-[11px] font-bold tabular-nums text-primary-foreground">{nOn}</span>}
          </button>
          <NewLeadAction primary />
        </div>
        {/* one thin line: what is shown and how many; tapping it opens the same sheet */}
        <button type="button" onClick={() => setShowFilters(true)}
          className="-my-1 flex min-h-8 cursor-pointer items-center gap-1 self-start rounded-lg text-left text-[13px] font-semibold text-[var(--haip-fg-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50">
          <span>{onStage ? label[chip] ?? "Stage" : "Needs action"}</span>
          {total != null && <span className="tabular-nums text-[var(--haip-fg-subtle)]">· {total}</span>}
          <ChevronDown size={14} aria-hidden className="text-[var(--haip-fg-subtle)]" />
        </button>
        {!onStage && nFilters > 0 && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Filters apply to the stage lists, not to Needs action.</p>}
        {q && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Searching the {onStage ? (list.data?.pages.flatMap(p => p.leads).length ?? 0) : needsLeads.length} leads loaded here{onStage && list.hasNextPage ? " · load more to search further" : ""}.</p>}

        {pending ? (
          <div className="grid gap-1.5" aria-busy="true">{[0, 1, 2, 3, 4].map(i => <Skeleton key={i} className="h-[72px] rounded-xl" />)}</div>
        ) : failed ? (
          <div className="haip-card"><EmptyState title="Couldn't load the leads" hint="Check your connection and try again."
            action={<button type="button" onClick={() => (onStage ? list.refetch() : needs.refetch())} className="haip-btn-secondary min-h-11">Try again</button>} /></div>
        ) : rows.length === 0 ? (
          <div className="haip-card"><EmptyState title={q ? "No leads match" : onStage ? `Nothing in ${label[chip] ?? "this stage"}` : "Nothing needs action"}
            hint={q ? `Try another name or ${booking}.` : onStage ? "Leads that reach this stage appear here." : "Every lead has had its next step."} /></div>
        ) : (
          <>
            <RowList label={onStage ? label[chip] : "Needs action"}>
              {rows.map(l => <Row key={l.inquiry_id} lead={l} stageLabel={onStage ? undefined : label[l.stage_key ?? ""]}
                heat={leadHeat(l, stages.find(s => s.key === l.stage_key))} canReveal={canRevealNumbers(role)} onOpen={() => setPicked(l)} />)}
            </RowList>
            {onStage && list.hasNextPage && (
              <button type="button" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage} className="haip-btn-secondary min-h-11">
                {list.isFetchingNextPage ? "Loading…" : `Show more (${list.data?.pages.flatMap(p => p.leads).length ?? 0} of ${total})`}
              </button>
            )}
          </>
        )}
      </div>

      <Fab label="New lead" onClick={() => setAdding(true)} />
      {adding && <AddLeadModal onClose={() => setAdding(false)} onCreated={() => setAdding(false)} />}
      <LeadRowSheet lead={picked} onClose={() => setPicked(null)} stages={stages} canReverse={role === "owner" || role === "manager"} />
      <LeadFiltersSheet open={showFilters} onClose={() => setShowFilters(false)} filters={filters} onChange={setFilters}
        views={items} view={chip} onView={setChip} />
    </div>
  );
}
