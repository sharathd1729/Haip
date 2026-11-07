"use client";
// Ops Staff: drivers, helpers and caretakers. They never log in; HAIP reaches them on WhatsApp (crew brief, photo reminders,
// alerts) once they agreed to it. GET/POST /ops/staff, PATCH /ops/staff/{id} (owner/manager). A driver's HMV licence is a
// paper on the server: a driver whose licence ends before a trip ends cannot be put on that trip.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useHydrated } from "@/lib/bookingAgenda";
import { canManageOps, DUTY_LABELS, expiryLevel, type OpsStaff } from "@/lib/ops";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";
import { OpsNav } from "@/components/ops/OpsNav";
import { StaffTabs } from "@/components/ops/StaffTabs";
import { input, label, Shell } from "@/components/ops/TripSheets";

const SHOWN_DUTIES = ["driver", "caretaker", "maintenance", "housekeeping", "ops_manager"];

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}

const fmt = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

interface Form { id?: string; name: string; phone: string; duties: string[]; optIn: boolean; licence: string; expires: string; active: boolean }
const EMPTY: Form = { name: "", phone: "", duties: ["driver"], optIn: true, licence: "", expires: "", active: true };

export default function OpsStaffPage() {
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const { toast } = useToast();
  const role = useSession().data?.user?.role;
  const manage = canManageOps(role);
  const [form, setForm] = useState<Form | null>(null);
  const [showAll, setShowAll] = useState(false);

  const { data, isPending, isError, refetch } = useQuery<OpsStaff[]>({
    queryKey: ["ops-staff", "all"], queryFn: () => api.get("/ops/staff?include_inactive=true").then(r => r.data), staleTime: 30_000,
  });
  const save = useMutation({
    mutationFn: (f: Form) => {
      const body = {
        name: f.name.trim(), phone: f.phone.trim(), duties: f.duties.map(duty => ({ duty })), whatsapp_opt_in: f.optIn,
        licence_number: f.duties.includes("driver") ? f.licence.trim() || null : null,
        licence_expires_on: f.duties.includes("driver") ? f.expires || null : null,
        ...(f.id ? { active: f.active } : {}),
      };
      return f.id ? api.patch(`/ops/staff/${f.id}`, body) : api.post("/ops/staff", body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ops-staff"] });
      qc.invalidateQueries({ queryKey: ["ops-today"] });
      toast({ title: "Saved", variant: "success" });
      setForm(null);
    },
    onError: e => toast({ title: "Not saved", description: errorText(e), variant: "error" }),
  });

  // Today in the browser's calendar, read only after hydration (the list renders only then).
  const today = hydrated ? new Date().toLocaleDateString("en-CA") : "";
  const rows = (data ?? []).filter(s => showAll || s.active);
  const edit = (s: OpsStaff) => setForm({
    id: s.id, name: s.name, phone: s.phone_e164, duties: s.duties.map(d => d.duty), optIn: !!s.whatsapp_opt_in_at,
    licence: s.licence_number ?? "", expires: s.licence_expires_on ?? "", active: s.active,
  });
  const toggleDuty = (d: string) => setForm(f => f && ({ ...f, duties: f.duties.includes(d) ? f.duties.filter(x => x !== d) : [...f.duties, d] }));

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 p-4 sm:p-6">
      <PageHeader title="Staff" subtitle="Drivers and helpers. They use WhatsApp, not HAIP."
        actions={manage ? <button type="button" className="haip-btn-primary min-h-12" onClick={() => setForm({ ...EMPTY })}>Add a person</button> : undefined} />
      <OpsNav />
      <StaffTabs />
      {!hydrated || isPending ? (
        <div className="flex flex-col gap-2" aria-busy="true"><Skeleton className="h-16" /><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
      ) : isError || !data ? (
        <Card><EmptyState title="Couldn't load your staff" hint="Check your connection, then try again."
          action={<button type="button" className="haip-btn-primary min-h-12" onClick={() => refetch()}>Try again</button>} /></Card>
      ) : rows.length === 0 ? (
        <Card><EmptyState title="No staff yet" hint="Add your drivers and helpers so you can put them on trips."
          action={manage ? <button type="button" className="haip-btn-primary min-h-12" onClick={() => setForm({ ...EMPTY })}>Add a person</button> : undefined} /></Card>
      ) : (
        <Card>
          <CardBody className="px-4 py-1">
            {rows.map(s => {
              const lvl = expiryLevel(s.licence_expires_on, today);
              const driver = s.duties.some(d => d.duty === "driver");
              return (
                <button key={s.id} type="button" disabled={!manage} onClick={() => edit(s)}
                  className={cn("flex min-h-[64px] w-full items-center gap-3 border-t border-[var(--haip-border)] py-2.5 text-left first:border-t-0 disabled:cursor-default",
                    !s.active && "opacity-60")}>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[16px] font-semibold">{s.name}</span>
                    <span className="block truncate text-[13px] text-[var(--haip-fg-subtle)]">
                      {s.duties.map(d => DUTY_LABELS[d.duty] ?? d.duty).join(", ") || "No duty set"}
                      {driver && (s.licence_expires_on ? ` · licence to ${fmt(s.licence_expires_on)}` : " · licence not entered")}
                    </span>
                  </span>
                  {!s.active ? <StatusPill tone="neutral">Not active</StatusPill>
                    : lvl ? <StatusPill tone={lvl === "red" ? "danger" : "warning"}>{lvl === "red" ? "Licence ending" : "Licence soon"}</StatusPill>
                    : !s.whatsapp_opt_in_at ? <StatusPill tone="warning">No WhatsApp OK</StatusPill> : null}
                </button>
              );
            })}
          </CardBody>
        </Card>
      )}
      {data && data.some(s => !s.active) && (
        <button type="button" className="self-start text-[14px] font-semibold text-primary" onClick={() => setShowAll(v => !v)}>
          {showAll ? "Hide people who left" : "Show people who left"}
        </button>
      )}

      <Shell open={!!form} onClose={() => setForm(null)} busy={save.isPending} title={form?.id ? "Edit person" : "Add a person"}
        submitLabel={form?.id ? "Save" : "Add"} description="Phone with country code, e.g. +91 98450 12345."
        onSubmit={() => form && save.mutate(form)}>
        {form && (
          <>
            <label className={label}>Name<input className={input} required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>
            <label className={label}>WhatsApp number<input className={input} required type="tel" inputMode="tel" value={form.phone}
              onChange={e => setForm({ ...form, phone: e.target.value })} /></label>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-[14px] font-semibold">What they do</legend>
              {SHOWN_DUTIES.map(d => (
                <label key={d} className="flex min-h-11 items-center gap-3 text-[15px]">
                  <input type="checkbox" className="size-5" checked={form.duties.includes(d)} onChange={() => toggleDuty(d)} />{DUTY_LABELS[d]}
                </label>
              ))}
            </fieldset>
            {form.duties.includes("driver") && (
              <>
                <label className={label}>HMV licence number<input className={input} value={form.licence} onChange={e => setForm({ ...form, licence: e.target.value })} /></label>
                <label className={label}>Licence valid until<input className={input} type="date" value={form.expires}
                  onChange={e => setForm({ ...form, expires: e.target.value })} /></label>
              </>
            )}
            <label className="flex min-h-11 items-center gap-3 text-[15px]">
              <input type="checkbox" className="size-5" checked={form.optIn} onChange={e => setForm({ ...form, optIn: e.target.checked })} />
              They agreed to get trip messages on WhatsApp
            </label>
            {form.id && (
              <label className="flex min-h-11 items-center gap-3 text-[15px]">
                <input type="checkbox" className="size-5" checked={!form.active} onChange={e => setForm({ ...form, active: !e.target.checked })} />
                Left the team (keep their history, stop messages)
              </label>
            )}
          </>
        )}
      </Shell>
    </div>
  );
}
