"use client";
// The phone Leads list's two sheets. LeadRowSheet: a lead's details without leaving the list (AI note in full, trip facts, who
// owns it) and its actions: Call, Move stage, Assign, Open lead. Move stage / Lost / Assign open the lead page's OWN sheets
// (lead-page/LeadSheets.tsx: PATCH /inquiries/{id}, the audited state-machine path; Lost asks for a reason; moving back asks
// for one too). LeadFiltersSheet: the Leads filters (the desktop bar's own controls) in a bottom sheet.
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Check, ExternalLink, Flag, Phone, UserPlus } from "@/lib/icons";
import { BottomSheet, OneLineSummary, RowTag, SheetActions, sheetActionCls } from "@/components/ui/kit";
import type { LeadCard } from "@/components/leads/LeadCard";
import { FilterControls, type LeadsFilters } from "@/components/leads/LeadsFilterBar";
import { LostSheet, OwnerSheet, StageSheet } from "@/components/leads/lead-page/LeadSheets";
import { SoldSheet } from "@/components/leads/lead-page/SoldSheet";
import type { PipelineStage } from "@/components/leads/lead-page/types";
import type { PipelineStageRow } from "@/hooks/usePipelineStages";
import { useDial } from "@/components/myday/useDial";
import { useSession } from "next-auth/react";
import { canRevealNumbers, useContactChoice } from "@/components/contact/ContactChoice";
import { cn, formatINR } from "@/lib/utils";
import { tripText } from "./leadRow";

type Sub = "stage" | "lost" | "won" | "owner" | null;

function facts(l: LeadCard): string[] {
  const party = [l.adults ? `${l.adults} adult${l.adults === 1 ? "" : "s"}` : null, l.children ? `${l.children} child${l.children === 1 ? "" : "ren"}` : null]
    .filter(Boolean).join(", ");
  const money = l.quoted_amount ? `quoted ${formatINR(l.quoted_amount)}` : l.budget_estimate ? `budget ${formatINR(l.budget_estimate)}` : null;
  return [tripText(l), party, l.occasion, money].filter((v): v is string => !!v);
}

export function LeadRowSheet({ lead, onClose, stages, canReverse }: {
  lead: LeadCard | null; onClose: () => void; stages: PipelineStageRow[]; canReverse: boolean;
}) {
  // The lead stays in view while one of its sub-sheets is open, even after the row sheet itself closes.
  const [sub, setSub] = useState<Sub>(null);
  const [held, setHeld] = useState<LeadCard | null>(null);
  const [wonStage, setWonStage] = useState<PipelineStage | null>(null);
  const l = lead ?? held;
  const dial = useDial(l?.display_name ?? "");
  const role = (useSession().data?.user as { role?: string } | undefined)?.role;
  // Call = My phone | Office line (components/contact/ContactChoice)
  const callChoice = useContactChoice({ kind: "call", inquiryId: l?.inquiry_id ?? "", name: l?.display_name ?? "", canReveal: canRevealNumbers(role),
    onOffice: () => { if (l) dial.mutate({ inquiry_id: l.inquiry_id }); } });
  const stage = stages.find(s => s.key === l?.stage_key);
  const open = (s: Sub) => { setHeld(lead); setSub(s); onClose(); };
  const done = () => { setSub(null); setHeld(null); };
  const hasPhone = !!l?.identity_signals?.includes("phone");
  if (!l) return null;
  return (
    <>
      <BottomSheet open={!!lead} onOpenChange={o => { if (!o) onClose(); }} title={l.display_name}
        description={[stage?.label, l.assigned_agent_name ?? "Unassigned", l.primary_channel].filter(Boolean).join(" · ")}
        footer={<SheetActions>
          {hasPhone && (
            <button type="button" className={sheetActionCls(true)} disabled={dial.isPending} onClick={() => { setHeld(lead); onClose(); callChoice.start(); }}>
              <Phone size={18} />{dial.isPending ? "Calling…" : "Call"}
            </button>
          )}
          <button type="button" className={sheetActionCls(!hasPhone)} onClick={() => open("stage")}><Flag size={18} />Move stage</button>
          <button type="button" className={sheetActionCls()} onClick={() => open("owner")}><UserPlus size={18} />Assign</button>
          <Link href={`/dashboard/leads/${l.inquiry_id}`} className={sheetActionCls()}><ExternalLink size={18} />Full page</Link>
        </SheetActions>}>
        <div className="grid gap-3">
          {facts(l).length > 0 && <div className="flex flex-wrap gap-1.5">{facts(l).map(f => <RowTag key={f}>{f}</RowTag>)}</div>}
          {l.ai_summary ? (
            <div className="grid gap-1 rounded-xl bg-[var(--haip-olive-bg)] px-3 py-2.5 text-[var(--haip-olive-fg)]">
              <span className="text-[12px] font-bold">AI note</span>
              <OneLineSummary text={l.ai_summary} className="text-[var(--haip-olive-fg)]" />
            </div>
          ) : <p className="text-[13px] text-[var(--haip-fg-subtle)]">No AI note yet.</p>}
          {l.ai_next_action && <p className="text-[13.5px] text-[var(--haip-fg-2)]"><span className="font-semibold">Next step: </span>{l.ai_next_action}</p>}
          {l.needs_agent_followup && l.needs_agent_followup_reason && (
            <p className="rounded-xl bg-[var(--haip-status-warning-bg)] px-3 py-2 text-[13px] text-[var(--haip-status-warning-fg)]">{l.needs_agent_followup_reason}</p>
          )}
        </div>
      </BottomSheet>
      <StageSheet open={sub === "stage"} onClose={done} inquiryId={l.inquiry_id} stages={stages} currentKey={l.stage_key}
        canReverse={canReverse} onLost={() => setSub("lost")} onWon={s => { setWonStage(s); setSub("won"); }} />
      {/* a list row does not know whether a booking is linked, so the sheet asks */}
      <SoldSheet open={sub === "won"} onClose={done} inquiryId={l.inquiry_id} name={l.display_name} stage={wonStage ?? undefined} />
      <LostSheet open={sub === "lost"} onClose={done} inquiryId={l.inquiry_id} name={l.display_name} lostStage={stages.find(s => s.is_closed_lost)} />
      <OwnerSheet open={sub === "owner"} onClose={done} inquiryId={l.inquiry_id} ownerId={l.assigned_agent_id} />
      {callChoice.sheet}
    </>
  );
}

export function LeadFiltersSheet({ open, onClose, filters, onChange, views, view, onView }: {
  open: boolean; onClose: () => void; filters: LeadsFilters; onChange: (f: LeadsFilters) => void;
  /** What the list shows: Needs action, then the workspace's own stages (never fixed names), each with its count. */
  views: { value: string; label: string; count?: number }[]; view: string; onView: (value: string) => void;
}) {
  const { data: users = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["users-lite"], queryFn: () => api.get("/users/lite").then(r => r.data), staleTime: 5 * 60_000, enabled: open,
  });
  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["properties-lite"], queryFn: () => api.get("/properties").then(r => r.data), staleTime: 5 * 60_000, enabled: open,
  });
  const active = Object.values(filters).filter(Boolean).length;
  const shown = views.find(v => v.value === view)?.count;          // the picked view's count, for "Show N leads"
  return (
    <BottomSheet open={open} onOpenChange={o => { if (!o) onClose(); }} title="Show and filter" description="Stage, owner, source, dates and more."
      footer={<button type="button" onClick={onClose} className="haip-btn-primary min-h-11 w-full cursor-pointer">
        {shown == null ? "Show leads" : `Show ${shown} ${shown === 1 ? "lead" : "leads"}`}</button>}>
      <div role="radiogroup" aria-label="Show" className="mb-4 grid gap-1.5">
        {views.map(v => {
          const on = v.value === view;
          return (
            <button key={v.value} type="button" role="radio" aria-checked={on} onClick={() => onView(v.value)}
              className={cn("flex min-h-11 w-full cursor-pointer items-center justify-between gap-2 rounded-xl border px-3 text-left text-[14.5px] font-semibold text-[var(--haip-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50",
                on ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)] bg-[var(--haip-card)]")}>
              <span className="min-w-0 truncate">{v.label}</span>
              <span className="flex shrink-0 items-center gap-2 tabular-nums text-[13px] text-[var(--haip-fg-subtle)]">
                {v.count ?? ""}{on && <Check size={16} className="text-primary" aria-hidden />}
              </span>
            </button>
          );
        })}
      </div>
      <FilterControls filters={filters} set={patch => onChange({ ...filters, ...patch })} clearAll={() => onChange({})}
        activeCount={active} users={users} properties={properties} layout="column" />
    </BottomSheet>
  );
}
