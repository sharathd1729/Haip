"use client";
// Lead page, "Valid enquiry?" (CRM reporting, 22 Oct 2026): a PERSON's review of the enquiry -- valid yes / no with three
// checks -- plus the lead type (guest / B2B / partner; only guests count in the guest lead numbers). The daily lead report
// shows these human answers apart from the automatic stage numbers. Backend: PUT /leads/{id}/validation and
// PUT /leads/{id}/lead-type (leads.write, audited); read from the lead detail (`lead_type`, `validation`).
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Loader2 } from "@/lib/icons";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { istDate } from "./format";
import type { LeadValidation } from "./types";

const TYPES = [
  { value: "guest", label: "Guest" },
  { value: "b2b", label: "B2B / trade" },
  { value: "partner", label: "Partner" },
] as const;
const CHECKS = [
  { key: "dates_confirmed", label: "Dates confirmed" },
  { key: "budget_fits", label: "Budget fits" },
  { key: "clear_intent", label: "Clear intent to book" },
] as const;
type CheckKey = (typeof CHECKS)[number]["key"];

const pill = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border px-3.5 text-[14px] font-semibold";

export function LeadReviewCard({ inquiryId, leadType, validation, canEdit }: {
  inquiryId: string; leadType?: string | null; validation?: LeadValidation | null; canEdit: boolean;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [checks, setChecks] = useState<Record<CheckKey, boolean>>({ dates_confirmed: false, budget_fits: false, clear_intent: false });
  const [note, setNote] = useState("");
  useEffect(() => {
    setChecks({ dates_confirmed: !!validation?.dates_confirmed, budget_fits: !!validation?.budget_fits, clear_intent: !!validation?.clear_intent });
    setNote(validation?.note ?? "");
  }, [validation]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["lead", inquiryId] }); qc.invalidateQueries({ queryKey: ["leads"] }); };
  const fail = () => toast({ variant: "error", title: "Not saved", description: "Try again." });
  const review = useMutation({
    mutationFn: (valid: boolean | null) => api.put(`/leads/${inquiryId}/validation`, valid === null ? { valid: null } : { valid, ...checks, note: note.trim() || null }),
    onSuccess: (_d, valid) => { toast({ variant: "success", title: valid === null ? "Review cleared" : "Review saved · logged" }); refresh(); },
    onError: fail,
  });
  const setType = useMutation({
    mutationFn: (lead_type: string) => api.put(`/leads/${inquiryId}/lead-type`, { lead_type }),
    onSuccess: () => { toast({ variant: "success", title: "Lead type changed · logged" }); refresh(); },
    onError: fail,
  });
  const status = validation?.status ?? null;
  const type = leadType || "guest";
  return (
    <Card>
      <CardHeader title="Valid enquiry?" description="Your call, not the AI's. It feeds the daily lead report." />
      <CardBody className="grid gap-3" data-testid="lead-review-card">
        <div className="grid gap-1.5">
          <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Lead type</span>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Lead type">
            {TYPES.map(t => (
              <button key={t.value} type="button" role="radio" aria-checked={type === t.value} disabled={!canEdit || setType.isPending}
                onClick={() => t.value !== type && setType.mutate(t.value)}
                className={cn(pill, "min-h-10", type === t.value ? "border-primary bg-[var(--haip-primary-tint)] text-primary" : "border-[var(--haip-border)] text-[var(--haip-fg-2)]", "disabled:opacity-60")}>
                {t.label}
              </button>
            ))}
          </div>
          {type !== "guest" && <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Not counted in the guest lead numbers.</p>}
        </div>

        <div className="grid gap-1.5">
          <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Checks</span>
          {CHECKS.map(c => (
            <label key={c.key} className="flex min-h-11 items-center gap-2.5 text-[14px] text-[var(--haip-fg)]">
              <input type="checkbox" className="size-5 accent-[var(--primary)]" disabled={!canEdit} checked={checks[c.key]}
                onChange={e => setChecks(v => ({ ...v, [c.key]: e.target.checked }))} />
              {c.label}
            </label>
          ))}
          <input className="min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:text-sm" maxLength={300}
            disabled={!canEdit} placeholder="Note (optional)" value={note} onChange={e => setNote(e.target.value)} />
        </div>

        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={review.isPending} onClick={() => review.mutate(true)}
              className={cn(pill, status === "valid" ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border-strong)] text-[var(--haip-fg-2)]", "disabled:opacity-60")}>
              {review.isPending && review.variables === true ? <Loader2 size={14} className="animate-spin" aria-hidden /> : status === "valid" ? <Check size={15} aria-hidden /> : null} Valid
            </button>
            <button type="button" disabled={review.isPending} onClick={() => review.mutate(false)}
              className={cn(pill, status === "invalid" ? "border-[var(--haip-status-danger-fg)] bg-[var(--haip-status-danger-bg)] text-[var(--haip-status-danger-fg)]" : "border-[var(--haip-border-strong)] text-[var(--haip-fg-2)]", "disabled:opacity-60")}>
              {status === "invalid" && <Check size={15} aria-hidden />} Not valid
            </button>
            {status && (
              <button type="button" disabled={review.isPending} onClick={() => review.mutate(null)}
                className="min-h-11 rounded-xl px-3 text-[13.5px] font-semibold text-[var(--haip-fg-muted)] disabled:opacity-60">Clear</button>
            )}
          </div>
        )}
        <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">
          {status ? `Marked ${status === "valid" ? "Valid" : "Not valid"}${validation?.by_name ? ` by ${validation.by_name}` : ""}${validation?.at ? ` · ${istDate(validation.at)}` : ""}`
            : "Not reviewed yet."}
        </p>
      </CardBody>
    </Card>
  );
}
