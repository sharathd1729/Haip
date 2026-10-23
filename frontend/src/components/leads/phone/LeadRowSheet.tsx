"use client";
// The phone Leads list's two sheets. LeadRowSheet: a lead's details without leaving the list (AI note in full, trip facts, who
// owns it) and its actions: Call, Move stage, Assign, Open lead. Move stage / Lost / Assign open the lead page's OWN sheets
// (lead-page/LeadSheets.tsx: PATCH /inquiries/{id}, the audited state-machine path; Lost asks for a reason; moving back asks
// for one too). LeadFiltersSheet: the Leads filters (the desktop bar's own controls) in a bottom sheet.
import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ExternalLink, Flag, Phone, UserPlus } from "@/lib/icons";
import { BottomSheet, OneLineSummary, RowTag, SheetActions, sheetActionCls } from "@/components/ui/kit";
import type { LeadCard } from "@/components/leads/LeadCard";
import { FilterControls, type LeadsFilters } from "@/components/leads/LeadsFilterBar";
import { LostSheet, OwnerSheet, StageSheet } from "@/components/leads/lead-page/LeadSheets";
import type { PipelineStageRow } from "@/hooks/usePipelineStages";
import { useDial } from "@/components/myday/useDial";
import { formatINR } from "@/lib/utils";
import { tripText } from "./leadRow";

type Sub = "stage" | "lost" | "owner" | null;

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
  const l = lead ?? held;
  const dial = useDial(l?.display_name ?? "");
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
            <button type="button" className={sheetActionCls(true)} disabled={dial.isPending} onClick={() => dial.mutate({ inquiry_id: l.inquiry_id })}>
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
        canReverse={canReverse} onLost={() => setSub("lost")} />
      <LostSheet open={sub === "lost"} onClose={done} inquiryId={l.inquiry_id} name={l.display_name} lostStage={stages.find(s => s.is_closed_lost)} />
      <OwnerSheet open={sub === "owner"} onClose={done} inquiryId={l.inquiry_id} ownerId={l.assigned_agent_id} />
    </>
  );
}

export function LeadFiltersSheet({ open, onClose, filters, onChange }: {
  open: boolean; onClose: () => void; filters: LeadsFilters; onChange: (f: LeadsFilters) => void;
}) {
  const { data: users = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["users-lite"], queryFn: () => api.get("/users/lite").then(r => r.data), staleTime: 5 * 60_000, enabled: open,
  });
  const { data: properties = [] } = useQuery<{ id: string; name: string }[]>({
    queryKey: ["properties-lite"], queryFn: () => api.get("/properties").then(r => r.data), staleTime: 5 * 60_000, enabled: open,
  });
  const active = Object.values(filters).filter(Boolean).length;
  return (
    <BottomSheet open={open} onOpenChange={o => { if (!o) onClose(); }} title="Filters" description="Owner, source, dates and more."
      footer={<button type="button" onClick={onClose} className="haip-btn-primary min-h-11 w-full">Show leads</button>}>
      <FilterControls filters={filters} set={patch => onChange({ ...filters, ...patch })} clearAll={() => onChange({})}
        activeCount={active} users={users} properties={properties} layout="column" />
    </BottomSheet>
  );
}
