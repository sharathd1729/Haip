"use client";
// After-call wrap-up (owner, 28 Nov 2026): what the agent does right after a call, shown first on the call page.
// In order: who it was (the name can be corrected; a name heard on the call is offered, never forced), the lead's stage (the
// workspace's own stages, never fixed names) and how warm the call was, then "From the call": the trip facts HAIP heard, each
// with the moment it was said (tap to play it) and a tick to save it on the lead, then the agent's note, then Save / Book.
// Nothing is written until the person saves: ticked facts go to the lead (PATCH /inquiries/{id}, the audited path the lead
// page uses), the note to the call (POST /calls/{id}/wrap-up, which also takes the call off the "needs wrap-up" list).
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn, formatINR } from "@/lib/utils";
import { Calendar, CalendarCheck, Check, ChevronDown, Flag, Gift, Heart, Loader2, MapPin, Play, Users, Wallet } from "@/lib/icons";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { usePipelineStages } from "@/hooks/usePipelineStages";
import { EditableName } from "@/components/leads/lead-page/EditableName";
import { LostSheet, StageSheet } from "@/components/leads/lead-page/LeadSheets";
import { SoldSheet } from "@/components/leads/lead-page/SoldSheet";
import type { LeadDetail, PipelineStage } from "@/components/leads/lead-page/types";
import { HEAT_CARD } from "@/components/leads/phone/leadRow";
import { istDate } from "@/components/leads/lead-page/format";

export interface CallFact { field: string; value: string | number; said_at?: number | null; quote?: string | null }
export interface WrapUpCall {
  id: string; inquiry_id?: string | null; guest_name?: string | null; needs_wrap_up?: boolean; wrap_up_notes?: string | null;
  transcription_status?: string | null; ai_score_status?: string | null;
  ai_insights?: { from_call?: CallFact[]; heard_name?: string | null; temperature?: { value?: string | null; reason?: string | null } | null } | null;
}

// what the call said -> where it is saved on the lead, and what the lead holds now
const FIELDS: Record<string, { label: string; icon: typeof Calendar; key: string; now: (l: LeadDetail) => string | number | null | undefined }> = {
  check_in: { label: "Check-in", icon: Calendar, key: "check_in", now: l => l.check_in?.slice(0, 10) },
  check_out: { label: "Check-out", icon: CalendarCheck, key: "check_out", now: l => l.check_out?.slice(0, 10) },
  adults: { label: "Adults", icon: Users, key: "adults", now: l => l.adults },
  children: { label: "Children", icon: Users, key: "children", now: l => l.children },
  budget: { label: "Budget", icon: Wallet, key: "budget", now: l => l.budget_estimate },
  occasion: { label: "Occasion", icon: Heart, key: "occasion", now: l => l.occasion },
  destination: { label: "Place asked for", icon: MapPin, key: "route_mentioned", now: l => l.trip?.route },
  guest_location: { label: "Coming from", icon: MapPin, key: "guest_location", now: l => l.guest_location },
  requests: { label: "Requests", icon: Gift, key: "special_requests", now: l => l.trip?.special_requests },
};

export function factText(field: string, value: string | number | null | undefined): string {
  if (value == null || value === "") return "";
  if (field === "check_in" || field === "check_out") return istDate(String(value).slice(0, 10));     // the lead page's own format
  if (field === "budget") return formatINR(Number(value));
  return String(value);
}
export const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const same = (a: unknown, b: unknown) => String(a ?? "").trim().toLowerCase() === String(b ?? "").trim().toLowerCase() || (a != null && b != null && Number(a) === Number(b));

const HEAT: Record<string, { label: string; cls: string }> = {
  hot: { label: "Hot", cls: HEAT_CARD.hot }, warm: { label: "Warm", cls: HEAT_CARD.warm }, cold: { label: "Cold", cls: HEAT_CARD.cold },
};
const chip = "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-[13px] font-semibold";

export function WrapUpCard({ call, onPlay }: { call: WrapUpCall; onPlay: (seconds: number) => void }) {
  const qc = useQueryClient();
  const router = useRouter();
  const { toast } = useToast();
  const role = (useSession().data?.user as { role?: string } | undefined)?.role ?? "";
  const canEdit = ["owner", "manager", "reservations", "concierge"].includes(role);
  const canBook = ["owner", "manager", "reservations"].includes(role);
  const inquiryId = call.inquiry_id ?? null;
  const facts = useMemo(() => (call.ai_insights?.from_call ?? []).filter(f => FIELDS[f.field]), [call.ai_insights]);
  const reading = ["queued", "pending", "processing"].includes(call.transcription_status ?? "") || call.ai_score_status === "processing";

  const leadQ = useQuery<LeadDetail>({
    queryKey: ["lead-detail", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}`).then(r => r.data), enabled: !!inquiryId, staleTime: 30_000,
  });
  const lead = leadQ.data;
  const { data: stages = [] } = usePipelineStages();
  const stage = stages.find(s => s.key === lead?.stage_key);
  const suggested = lead?.autopilot?.suggestion?.status === "suggested" ? lead.autopilot.suggestion.to_stage_label : null;
  const [sheet, setSheet] = useState<"stage" | "lost" | "won" | null>(null);
  const [wonStage, setWonStage] = useState<PipelineStage | null>(null);

  // A fact is ticked when the lead does not already hold it; the person can untick anything.
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (!lead) return;
    setPicked(Object.fromEntries(facts.map(f => [f.field, !same(FIELDS[f.field].now(lead), f.value)])));
  }, [lead, facts]);
  const [note, setNote] = useState(call.wrap_up_notes ?? "");
  useEffect(() => { setNote(call.wrap_up_notes ?? ""); }, [call.id, call.wrap_up_notes]);

  const heard = call.ai_insights?.heard_name?.trim() || null;
  const offerName = !!heard && !!lead && !same(heard, lead.display_name) && !(lead.display_name ?? "").toLowerCase().includes(heard.toLowerCase());
  const useName = useMutation({
    mutationFn: () => api.patch(`/inquiries/${inquiryId}`, { guest_name: heard }),
    onSuccess: () => { toast({ variant: "success", title: "Name saved" }); refresh(); },
    onError: () => toast({ variant: "error", title: "Name not saved", description: "Please try again." }),
  });

  const toSave = facts.filter(f => picked[f.field]);
  function refresh() {
    qc.invalidateQueries({ queryKey: ["lead-detail", inquiryId] });
    qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
    qc.invalidateQueries({ queryKey: ["call", call.id] });
    qc.invalidateQueries({ queryKey: ["calls"] });
  }
  const save = useMutation({
    mutationFn: async (_then: "stay" | "book") => {
      if (inquiryId && canEdit && toSave.length) {
        await api.patch(`/inquiries/${inquiryId}`, Object.fromEntries(toSave.map(f => [FIELDS[f.field].key, f.value])));
      }
      await api.post(`/calls/${call.id}/wrap-up`, { notes: note.trim() });
    },
    onSuccess: (_d, then) => {
      refresh();
      if (then === "book" && inquiryId) { router.push(`/dashboard/bookings/new?inquiry=${encodeURIComponent(inquiryId)}`); return; }
      toast({ variant: "success", title: "Wrap-up saved", description: toSave.length ? `${toSave.length} ${toSave.length === 1 ? "detail" : "details"} saved on the lead.` : undefined });
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Wrap-up not saved", description: typeof d === "string" ? d : "Nothing was lost. Please try again." });
    },
  });

  const heat = HEAT[(call.ai_insights?.temperature?.value ?? "").toLowerCase()];
  const done = call.needs_wrap_up === false && !reading;

  return (
    <section aria-label="After-call wrap-up" className="haip-card grid gap-3 p-3.5 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[15px] font-bold text-[var(--haip-fg)]">Wrap up this call</h2>
        {call.needs_wrap_up ? <span className="rounded-full bg-[var(--haip-accent-light)] px-2.5 py-1 text-[12px] font-bold text-[var(--haip-accent-ink)]">To do</span>
          : done ? <span className="inline-flex items-center gap-1 rounded-full bg-[var(--haip-status-success-bg)] px-2.5 py-1 text-[12px] font-bold text-[var(--haip-status-success-fg)]"><Check size={12} aria-hidden />Saved</span> : null}
      </div>

      {/* who + stage + how warm */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {inquiryId && lead ? (
          <EditableName inquiryId={inquiryId} name={lead.display_name} canEdit={canEdit} className="truncate text-[16px] font-bold text-[var(--haip-fg)]" />
        ) : (
          <p className="text-[16px] font-bold text-[var(--haip-fg)]">{call.guest_name || <span className="text-[var(--haip-fg-subtle)]">No name yet</span>}</p>
        )}
        {inquiryId && lead && (
          <button type="button" onClick={() => setSheet("stage")} disabled={!canEdit} aria-label={`Stage: ${stage?.label ?? "not set"}. Change`}
            className={cn(chip, "cursor-pointer border-[var(--haip-border)] bg-[var(--haip-card)] text-[var(--haip-fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-default")}>
            <Flag size={14} aria-hidden className="text-[var(--haip-fg-subtle)]" />{stage?.label ?? "Stage"}{canEdit && <ChevronDown size={13} aria-hidden className="text-[var(--haip-fg-subtle)]" />}
          </button>
        )}
        {heat && <span className={cn(chip, "!min-h-8 text-[var(--haip-fg)]", heat.cls)} title={call.ai_insights?.temperature?.reason ?? undefined}>{heat.label}</span>}
      </div>
      {offerName && canEdit && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-[var(--haip-fg-2)]">
          Heard on the call: <strong className="text-[var(--haip-fg)]">{heard}</strong>
          <button type="button" onClick={() => useName.mutate()} disabled={useName.isPending}
            className="min-h-9 cursor-pointer rounded-lg px-2 font-semibold text-primary hover:bg-[var(--haip-surface)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-60">Use this name</button>
        </p>
      )}
      {suggested && suggested !== stage?.label && <p className="text-[13px] text-[var(--haip-fg-2)]">Suggested stage: <strong className="text-[var(--haip-fg)]">{suggested}</strong>. {lead?.autopilot?.suggestion?.reason}</p>}

      {/* from the call */}
      <div className="grid gap-1.5">
        <h3 className="text-[12.5px] font-bold text-[var(--haip-fg-2)]">From the call</h3>
        {reading ? (
          <div className="grid gap-1.5" aria-busy="true" aria-label="HAIP is reading the call">
            <Skeleton className="h-11 rounded-xl" /><Skeleton className="h-11 rounded-xl" />
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">HAIP is reading the call. What was said appears here in about a minute.</p>
          </div>
        ) : facts.length === 0 ? (
          <p className="rounded-xl bg-[var(--haip-surface)] px-3 py-2.5 text-[13px] text-[var(--haip-fg-2)]">No dates, guests or budget were heard on this call. Add what you learned in the note below.</p>
        ) : (
          <ul className="grid gap-1.5">
            {facts.map(f => {
              const meta = FIELDS[f.field];
              const Icon = meta.icon;
              const now = lead ? meta.now(lead) : null;
              const already = !!lead && same(now, f.value);
              const id = `wrap-${call.id}-${f.field}`;
              return (
                <li key={f.field} className="flex min-h-12 items-center gap-2.5 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] py-1 pl-3 pr-1.5">
                  <Icon size={16} aria-hidden className="shrink-0 text-[var(--haip-fg-subtle)]" />
                  <label htmlFor={id} className="grid min-w-0 flex-1 cursor-pointer gap-0.5">
                    {/* what the lead holds now sits on the label line, so the value said on the call is never cut short */}
                    <span className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{meta.label}
                      {already ? <span className="text-[var(--haip-status-success-fg)]">on the lead</span>
                        : now != null && now !== "" ? <span className="font-medium">lead has {factText(f.field, now)}</span> : null}
                    </span>
                    <span className="break-words text-[14.5px] font-bold text-[var(--haip-fg)]">{factText(f.field, f.value)}</span>
                  </label>
                  {f.said_at != null && (
                    <button type="button" onClick={() => onPlay(f.said_at!)} title={f.quote ?? undefined} aria-label={`Play where this was said, at ${clock(f.said_at)}`}
                      className="inline-flex min-h-11 shrink-0 cursor-pointer items-center gap-1 rounded-lg px-2 text-[12.5px] font-semibold tabular-nums text-[var(--haip-dom-call-ink)] hover:bg-[var(--haip-dom-call-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50">
                      <Play size={13} aria-hidden />{clock(f.said_at)}
                    </button>
                  )}
                  <input id={id} type="checkbox" checked={!!picked[f.field]} disabled={!inquiryId || !canEdit || already}
                    onChange={e => setPicked(p => ({ ...p, [f.field]: e.target.checked }))} aria-label={`Save ${meta.label} on the lead`}
                    className="mx-2 size-5 shrink-0 cursor-pointer accent-[var(--primary)] disabled:cursor-default" />
                </li>
              );
            })}
          </ul>
        )}
        {!inquiryId && facts.length > 0 && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">This call is not linked to a lead, so its details cannot be saved on one. Your note is still kept with the call.</p>}
      </div>

      <label className="grid gap-1 text-[12.5px] font-bold text-[var(--haip-fg-2)]">Your note
        <textarea value={note} onChange={e => setNote(e.target.value)} rows={2} maxLength={2000} placeholder="What was agreed, what to do next"
          className="min-h-[72px] w-full rounded-xl border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 py-2 text-[16px] font-normal text-[var(--haip-fg)]" />
      </label>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => save.mutate("stay")} disabled={save.isPending}
          className="inline-flex min-h-11 flex-1 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-xl bg-primary px-4 text-[14.5px] font-semibold text-primary-foreground active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 disabled:opacity-60">
          {save.isPending && <Loader2 size={15} className="motion-safe:animate-spin" aria-hidden />}
          {inquiryId && canEdit && toSave.length ? `Save ${toSave.length} to lead` : "Save wrap-up"}
        </button>
        {inquiryId && canBook && (
          <button type="button" onClick={() => save.mutate("book")} disabled={save.isPending}
            className="inline-flex min-h-11 flex-1 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-xl border border-[var(--haip-dom-book-bd)] bg-[var(--haip-dom-book-bg)] px-4 text-[14.5px] font-semibold text-[var(--haip-dom-book-ink)] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:opacity-60">
            <CalendarCheck size={15} aria-hidden />Save and book
          </button>
        )}
        {inquiryId && <Link href={`/dashboard/leads/${inquiryId}`} className="inline-flex min-h-11 items-center rounded-xl px-3 text-[13.5px] font-semibold text-primary hover:underline">Open lead</Link>}
      </div>

      {inquiryId && lead && (<>
        <StageSheet open={sheet === "stage"} onClose={() => setSheet(null)} inquiryId={inquiryId} stages={stages} currentKey={lead.stage_key}
          canReverse={["owner", "manager"].includes(role)} onLost={() => setSheet("lost")} onWon={s => { setWonStage(s); setSheet("won"); }} />
        <SoldSheet open={sheet === "won"} onClose={() => setSheet(null)} inquiryId={inquiryId} name={lead.display_name} stage={wonStage ?? undefined} />
        <LostSheet open={sheet === "lost"} onClose={() => setSheet(null)} inquiryId={inquiryId} name={lead.display_name} lostStage={stages.find(s => s.is_closed_lost)} />
      </>)}
    </section>
  );
}
