"use client";
// Settings > Lead rules (owner / manager). The automatic valid-lead rule (KPI D-28): a person's review always wins, the rule
// decides the rest. A missing check-in date is a note, never a reason to call a lead invalid unless switched on here.
// Backend: GET/PUT /lead-validity/settings (lead_validity, audited).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, EmptyState, PageHeader } from "@/components/ui/kit";

interface Rule {
  enabled: boolean; require_name: boolean; require_phone: boolean; require_check_in: boolean; require_location: boolean;
  allowed_locations: string[]; location_field: "guest_location" | "pickup" | "guest_city";
  location_fields: { value: string; label: string }[];
}

const CHECKS: { key: keyof Rule; label: string; hint: string }[] = [
  { key: "require_name", label: "Needs a name", hint: "Not “Unknown” and not a phone number." },
  { key: "require_phone", label: "Needs a phone number", hint: "A number HAIP can call or WhatsApp." },
  { key: "require_check_in", label: "Needs a check-in date", hint: "Off: a lead without a date stays valid and shows “No check-in date yet”." },
  { key: "require_location", label: "Location must be known", hint: "Off: an unknown location is a note; a different city is still invalid." },
];

const input = "min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)] sm:text-sm";

export default function LeadRulesPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Rule>({ queryKey: ["lead-validity-settings"], queryFn: () => api.get("/lead-validity/settings").then(r => r.data) });
  const [rule, setRule] = useState<Rule | null>(null);
  const [places, setPlaces] = useState("");
  useEffect(() => { if (q.data) { setRule(q.data); setPlaces(q.data.allowed_locations.join(", ")); } }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put("/lead-validity/settings", {
      enabled: rule!.enabled, require_name: rule!.require_name, require_phone: rule!.require_phone,
      require_check_in: rule!.require_check_in, require_location: rule!.require_location, location_field: rule!.location_field,
      allowed_locations: places.split(",").map(x => x.trim()).filter(Boolean),
    }).then(r => r.data as Rule),
    onSuccess: d => { qc.setQueryData(["lead-validity-settings"], d); qc.invalidateQueries({ queryKey: ["leads"] }); toast({ variant: "success", title: "Saved · logged" }); },
    onError: () => toast({ variant: "error", title: "Not saved", description: "Try again." }),
  });

  return (
    <div className="grid gap-4">
      <PageHeader title="Lead rules" subtitle="What counts as a valid lead, and the daily lead report email." />
      <Card>
        <CardHeader title="Valid-lead rule" description="A person's review on the lead always wins. The rule decides the leads nobody has reviewed." />
        <CardBody className="grid gap-3">
          {q.isPending ? (
            <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading…</p>
          ) : q.isError || !rule ? (
            <EmptyState title="Couldn't load the rule" hint="Check your connection and try again."
              action={<button type="button" onClick={() => q.refetch()} className="min-h-11 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground">Try again</button>} />
          ) : (
            <>
              <label className="flex min-h-11 items-center gap-2.5 text-[14.5px] font-semibold text-[var(--haip-fg)]">
                <input type="checkbox" className="size-5 accent-[var(--primary)]" checked={rule.enabled} onChange={e => setRule({ ...rule, enabled: e.target.checked })} />
                Use the automatic rule
              </label>
              {CHECKS.map(c => (
                <label key={c.key} className="flex min-h-11 items-start gap-2.5 border-t border-[var(--haip-border)] pt-3 text-[14px] text-[var(--haip-fg)]">
                  <input type="checkbox" className="mt-0.5 size-5 accent-[var(--primary)]" disabled={!rule.enabled} checked={!!rule[c.key]}
                    onChange={e => setRule({ ...rule, [c.key]: e.target.checked })} />
                  <span><span className="block font-semibold">{c.label}</span><span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{c.hint}</span></span>
                </label>
              ))}
              <label className="grid gap-1 border-t border-[var(--haip-border)] pt-3">
                <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Allowed locations (comma separated; empty = any)</span>
                <input className={input} disabled={!rule.enabled} value={places} onChange={e => setPlaces(e.target.value)} placeholder="Bengaluru, Bangalore" />
              </label>
              <label className="grid gap-1">
                <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">Where the guest's location is read from</span>
                <select className={input} disabled={!rule.enabled} value={rule.location_field}
                  onChange={e => setRule({ ...rule, location_field: e.target.value as Rule["location_field"] })}>
                  {rule.location_fields.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                </select>
              </label>
              <button type="button" disabled={save.isPending} onClick={() => save.mutate()}
                className="inline-flex min-h-11 items-center justify-center justify-self-start gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60">
                {save.isPending && <Loader2 size={14} className="animate-spin" aria-hidden />} Save rule
              </button>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
