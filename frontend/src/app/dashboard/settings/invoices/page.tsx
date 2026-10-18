"use client";
// Settings > Invoice details: what is printed on invoices and receipts (legal name, GSTIN, address, state, SAC, logo,
// number prefixes), the automatic balance reminder switch, and the WhatsApp booking templates.
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, PageHeader } from "@/components/ui/kit";
import { BookingTemplatesCard } from "@/components/settings/BookingTemplatesCard";
import { gstinProblem, type InvoiceProfile, type InvoiceSettings } from "@/lib/invoices";

const field = "mt-1 w-full min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base text-[var(--haip-fg)] focus:outline-none focus:ring-2 focus:ring-primary sm:min-h-10 sm:text-sm";
const label = "block text-xs font-medium text-[var(--haip-fg-subtle)]";
const RATES = [0, 5, 12, 18];

/** FastAPI validation errors arrive as a list; show the first one in words. */
function saveError(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0] && typeof d[0].msg === "string") return String(d[0].msg).replace(/^Value error, /, "");
  return "Could not save. Check the fields and try again.";
}

function financialYear(d = new Date()): string {
  const start = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  return `${start}-${String(start + 1).slice(-2)}`;
}

export default function InvoiceSettingsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const { data, isLoading, isError, refetch } = useQuery<InvoiceSettings>({
    queryKey: ["invoice-settings"], queryFn: () => api.get("/settings/invoice-profile").then(r => r.data),
  });
  const [form, setForm] = useState<InvoiceProfile | null>(null);
  const [reminders, setReminders] = useState(false);
  useEffect(() => { if (data) { setForm(data.profile); setReminders(data.payments.auto_balance_reminder); } }, [data]);

  const save = useMutation({
    mutationFn: () => api.put<InvoiceSettings>("/settings/invoice-profile", { profile: form, payments: { auto_balance_reminder: reminders } }),
    onSuccess: res => { queryClient.setQueryData(["invoice-settings"], res.data); toast({ variant: "success", title: "Invoice details saved" }); },
    onError: e => toast({ variant: "error", title: saveError(e) }),
  });
  const logo = useMutation({
    mutationFn: (file: File | null) => {
      if (!file) return api.delete<InvoiceSettings>("/settings/invoice-profile/logo");
      const body = new FormData();
      body.append("file", file);
      return api.post<InvoiceSettings>("/settings/invoice-profile/logo", body);
    },
    onSuccess: res => { queryClient.setQueryData(["invoice-settings"], res.data); toast({ variant: "success", title: "Logo updated" }); },
    onError: e => toast({ variant: "error", title: saveError(e) }),
  });

  if (isLoading || (!form && !isError)) {
    return <div className="mx-auto max-w-2xl space-y-4 p-4 sm:p-6"><Skeleton className="h-10 w-56 rounded-lg" /><Skeleton className="h-96 rounded-2xl" /></div>;
  }
  if (isError || !data || !form) {
    return (
      <div role="alert" className="mx-auto max-w-2xl p-6 py-16 text-center">
        <p className="text-base font-semibold text-[var(--haip-fg)]">Couldn&apos;t load invoice details</p>
        <p className="mt-1 text-sm text-[var(--haip-fg-subtle)]">Only owners and managers can see this page.</p>
        <button type="button" onClick={() => refetch()} className="mt-4 min-h-11 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground">Try again</button>
      </div>
    );
  }

  const set = <K extends keyof InvoiceProfile>(k: K, v: InvoiceProfile[K]) => setForm(f => f && { ...f, [k]: v });
  const text = (k: "legal_name" | "gstin" | "address" | "sac_code") => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    set(k, e.target.value || null);
  const gstinError = form.gstin ? gstinProblem(form.gstin, data.states) : null;
  const stateMismatch = form.gstin && !gstinError && form.state_code && form.gstin.slice(0, 2) !== form.state_code;
  const fy = financialYear();

  return (
    <div className="mx-auto max-w-2xl space-y-5 p-4 sm:p-6">
      <PageHeader title="Invoice details" subtitle="Printed on every invoice and receipt HAIP issues when a guest pays." />

      {data.missing.length > 0 && (
        <p className="rounded-lg border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-sm text-[var(--haip-status-warning-fg)]">
          Invoices can&apos;t be issued yet. Add the {data.missing.join(", ")} and save.
        </p>
      )}

      <Card>
        <CardHeader title="Your business" description="As registered for GST. Issued invoices keep what was here when they were issued." />
        <CardBody className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className={cn(label, "sm:col-span-2")}>Legal name
            <input className={field} value={form.legal_name ?? ""} onChange={text("legal_name")} placeholder="Ratha Journeys LLP" autoComplete="organization" />
          </label>
          <label className={label}>GSTIN <span className="font-normal">(leave empty if not registered)</span>
            <input className={cn(field, "uppercase")} value={form.gstin ?? ""} maxLength={15} onChange={text("gstin")} placeholder="29ABCDE1234F1Z5"
              aria-invalid={!!gstinError} aria-describedby="gstin-help" autoCapitalize="characters" spellCheck={false} />
            <span id="gstin-help" className={cn("mt-1 block text-xs", gstinError || stateMismatch ? "text-[var(--haip-status-danger-fg)]" : "text-[var(--haip-fg-subtle)]")}>
              {gstinError ?? (stateMismatch ? `This GSTIN is registered in ${data.states[form.gstin!.slice(0, 2)]}.` : "Without a GSTIN no GST is charged on invoices.")}
            </span>
          </label>
          <label className={label}>State
            <select className={field} value={form.state_code ?? ""} onChange={e => set("state_code", e.target.value || null)}>
              <option value="">Choose a state</option>
              {Object.entries(data.states).sort((a, b) => a[1].localeCompare(b[1])).map(([code, name]) => <option key={code} value={code}>{name} ({code})</option>)}
            </select>
          </label>
          <label className={cn(label, "sm:col-span-2")}>Address
            <textarea rows={3} className={cn(field, "py-2")} value={form.address ?? ""} onChange={text("address")} placeholder="Street, area, city, PIN" />
          </label>
          <label className={label}>SAC code
            <input className={field} inputMode="numeric" value={form.sac_code ?? ""} onChange={text("sac_code")} placeholder="Ask your accountant" />
          </label>
          <label className={label}>GST rate
            <select className={field} value={form.gst_rate} onChange={e => set("gst_rate", Number(e.target.value))} disabled={!form.gstin}>
              {RATES.map(r => <option key={r} value={r}>{r}%</option>)}
            </select>
            <span className="mt-1 block text-xs text-[var(--haip-fg-subtle)]">Booking amounts include GST; the invoice shows it split out.</span>
          </label>
          <label className={label}>Invoice number prefix
            <input className={cn(field, "uppercase")} value={form.invoice_prefix} maxLength={10} onChange={e => set("invoice_prefix", e.target.value.toUpperCase())} />
            <span className="mt-1 block text-xs text-[var(--haip-fg-subtle)]">Next looks like {form.invoice_prefix || "INV"}/{fy}/0001</span>
          </label>
          <label className={label}>Receipt number prefix
            <input className={cn(field, "uppercase")} value={form.receipt_prefix} maxLength={10} onChange={e => set("receipt_prefix", e.target.value.toUpperCase())} />
            <span className="mt-1 block text-xs text-[var(--haip-fg-subtle)]">Receipts for later payments: {form.receipt_prefix || "RCPT"}/{fy}/0001</span>
          </label>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Logo" description="PNG, JPG or WebP, up to 2 MB. Printed at the top left of every invoice." />
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex h-16 w-40 items-center justify-center rounded-lg border border-dashed border-[var(--haip-border)] bg-[var(--haip-surface)]">
              {data.logo_url
                ? <img src={data.logo_url} alt="Invoice logo" className="max-h-14 max-w-36 object-contain" />
                : <span className="text-xs text-[var(--haip-fg-subtle)]">No logo</span>}
            </div>
            <div className="flex flex-wrap gap-2">
              <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Choose a logo file"
                onChange={e => { const f = e.target.files?.[0]; if (f) logo.mutate(f); e.target.value = ""; }} />
              <button type="button" onClick={() => fileRef.current?.click()} disabled={logo.isPending}
                className="min-h-11 rounded-lg border border-[var(--haip-border)] px-3 text-sm font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50 sm:min-h-9">
                {logo.isPending ? "Uploading..." : data.logo_source === "uploaded" ? "Replace logo" : "Upload a logo"}
              </button>
              {data.logo_source === "uploaded" && (
                <button type="button" onClick={() => logo.mutate(null)} disabled={logo.isPending}
                  className="min-h-11 px-2 text-sm text-[var(--haip-fg-subtle)] hover:text-[var(--haip-fg)] sm:min-h-9">Remove</button>
              )}
            </div>
          </div>
          <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg-2)]">
            <input type="checkbox" className="size-5" checked={form.use_branding_logo} onChange={e => set("use_branding_logo", e.target.checked)} />
            Use the Branding page&apos;s logo when none is uploaded here
          </label>
          {data.logo_source === "branding" && <p className="text-xs text-[var(--haip-fg-subtle)]">Showing the logo from Settings &gt; Branding.</p>}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Balance reminders" />
        <CardBody>
          <label className="flex min-h-11 items-start gap-3 text-sm text-[var(--haip-fg-2)]">
            <input type="checkbox" className="mt-0.5 size-5 flex-shrink-0" checked={reminders} onChange={e => setReminders(e.target.checked)} />
            <span>
              Send the guest a payment link on WhatsApp 3 days before each instalment is due, once per instalment.
              <span className="mt-0.5 block text-xs text-[var(--haip-fg-subtle)]">Needs Razorpay connected and the balance reminder template approved by Meta. Off until you switch it on.</span>
            </span>
          </label>
        </CardBody>
      </Card>

      <div className="sticky bottom-[calc(60px+env(safe-area-inset-bottom))] z-10 flex justify-end sm:bottom-4">
        <button type="button" onClick={() => save.mutate()} disabled={save.isPending || !!gstinError}
          className="min-h-11 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground shadow-sm disabled:opacity-50">
          {save.isPending ? "Saving..." : "Save invoice details"}
        </button>
      </div>

      <BookingTemplatesCard />
    </div>
  );
}
