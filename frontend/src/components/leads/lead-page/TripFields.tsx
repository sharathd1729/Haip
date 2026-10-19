"use client";
// Trip fields, edited in place: tap a value, change it, Enter or leave the field to save (PATCH /inquiries/{id}),
// Escape to cancel. Nights are worked out from the dates. Availability per vehicle comes with the feed.
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Pencil, Truck } from "@/lib/icons";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { inr, istDate, nights } from "./format";
import type { LeadDetail, LeadFeed } from "./types";

type Kind = "text" | "date" | "number";
interface Field { key: string; label: string; kind: Kind; wide?: boolean; value: string; display: string; readOnly?: boolean }

export function TripFields({ lead, feed, canEdit }: { lead: LeadDetail; feed?: LeadFeed; canEdit: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const trip = feed?.trip ?? {};
  const n = nights(lead.check_in, lead.check_out);

  const save = useMutation({
    mutationFn: (patch: Record<string, string | number>) => api.patch(`/inquiries/${lead.inquiry_id}`, patch),
    onSuccess: () => {
      toast({ variant: "success", title: "Trip details saved" });
      qc.invalidateQueries({ queryKey: ["lead", lead.inquiry_id] });
      qc.invalidateQueries({ queryKey: ["lead-feed", lead.inquiry_id] });
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast({ variant: "error", title: "Not saved", description: typeof d === "string" ? d : "Please try again." });
    },
  });

  const fields: Field[] = [
    { key: "route_mentioned", label: "Destination / route", kind: "text", value: trip.route ?? "", display: trip.route || "Add", wide: true },
    { key: "check_in", label: "Check-in", kind: "date", value: lead.check_in ?? "", display: lead.check_in ? istDate(lead.check_in) : "Add" },
    { key: "check_out", label: "Check-out", kind: "date", value: lead.check_out ?? "", display: lead.check_out ? istDate(lead.check_out) : "Add" },
    { key: "nights", label: "Nights", kind: "text", value: "", display: n == null ? "—" : `${n} night${n === 1 ? "" : "s"}`, readOnly: true },
    { key: "adults", label: "Adults", kind: "number", value: lead.adults ? String(lead.adults) : "", display: lead.adults ? String(lead.adults) : "Add" },
    { key: "children", label: "Children", kind: "number", value: lead.children ? String(lead.children) : "", display: lead.children ? String(lead.children) : "None" },
    { key: "pickup", label: "Pickup", kind: "text", value: trip.pickup ?? "", display: trip.pickup || "Add" },
    { key: "budget", label: "Budget (₹)", kind: "number", value: lead.budget_estimate ? String(lead.budget_estimate) : "",
      display: lead.budget_range_label || (lead.budget_estimate ? inr(lead.budget_estimate) : "Add") },
    { key: "occasion", label: "Occasion", kind: "text", value: lead.occasion ?? "", display: lead.occasion || "Add" },
    { key: "special_requests", label: "Special requests", kind: "text", value: trip.special_requests ?? "", display: trip.special_requests || "Add", wide: true },
  ];

  function commit(f: Field) {
    setEditing(null);
    const v = draft.trim();
    if (v === f.value) return;
    if (f.kind === "date") {
      const ci = f.key === "check_in" ? v : lead.check_in;
      const co = f.key === "check_out" ? v : lead.check_out;
      if (!v) return;
      if (ci && co && co < ci) { toast({ variant: "error", title: "Check-out must be after check-in" }); return; }
    }
    if (f.kind === "number") {
      if (!v) return;
      const num = Number(v);
      if (!Number.isFinite(num) || num < 0) { toast({ variant: "error", title: `${f.label}: enter a number` }); return; }
      save.mutate({ [f.key]: f.key === "budget" ? num : Math.round(num) });
      return;
    }
    save.mutate({ [f.key]: v });
  }

  const vehicles = feed?.availability ?? [];
  return (
    <Card>
      <CardHeader title="Trip" description={canEdit ? "Tap a value to change it" : undefined} />
      <CardBody className="grid gap-3 pt-1">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
          {fields.map(f => (
            <div key={f.key} className={cn("min-w-0", f.wide && "col-span-2")}>
              <dt className="pl-2 text-[12px] font-semibold text-[var(--haip-fg-subtle)]">{f.label}</dt>
              <dd>
                {editing === f.key ? (
                  <input autoFocus type={f.kind} inputMode={f.kind === "number" ? "numeric" : undefined} value={draft} aria-label={f.label}
                    onChange={e => setDraft(e.target.value)} onBlur={() => commit(f)}
                    onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); commit(f); } if (e.key === "Escape") setEditing(null); }}
                    className="min-h-11 w-full rounded-lg border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-2.5 text-[16px] text-[var(--haip-fg)]" />
                ) : f.readOnly || !canEdit ? (
                  <p className="flex min-h-11 items-center px-2 text-[14.5px] font-medium text-[var(--haip-fg)]">{f.display}</p>
                ) : (
                  <button type="button" onClick={() => { setDraft(f.value); setEditing(f.key); }} aria-label={`${f.label}: ${f.display}, edit`}
                    className="group flex min-h-11 w-full items-center justify-between gap-1.5 rounded-lg border border-dashed border-transparent px-2 text-left text-[14.5px] font-medium text-[var(--haip-fg)] hover:border-[var(--haip-border-strong)] hover:bg-[var(--haip-surface)]">
                    <span className={cn("min-w-0 break-words", (f.display === "Add" || f.display === "None") && "text-[var(--haip-fg-subtle)]")}>{f.display}</span>
                    <Pencil size={13} className="shrink-0 text-[var(--haip-fg-subtle)] opacity-50 group-hover:opacity-100" aria-hidden />
                  </button>
                )}
              </dd>
            </div>
          ))}
        </dl>
        {vehicles.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {vehicles.map(v => (
              <StatusPill key={v.property_id} tone={v.free ? "success" : "danger"}><Truck size={12} aria-hidden /> {v.name} {v.free ? "free" : "booked"}</StatusPill>
            ))}
            <span className="text-[12.5px] text-[var(--haip-fg-subtle)]">for these dates</span>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
