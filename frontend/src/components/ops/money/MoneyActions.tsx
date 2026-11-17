"use client";
// Money actions shared by Ops › Money and the ops file's Money card (workspace redesign Phase 4). Both go through the
// booking's own endpoints, so the rules, audit and Razorpay stay in one place: POST /bookings/{id}/payments (record a
// payment) and POST /bookings/{id}/payment-links {send_whatsapp} (a Razorpay link for the balance, sent on WhatsApp when
// it can go, else shown to copy). Owner, manager and reservations only (the server's _EDIT roles).
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import api from "@/lib/api";
import { errorMessage } from "@/lib/bookings";
import { Drawer } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";

export const MONEY_EDIT_ROLES = ["owner", "manager", "reservations"];
const METHODS = [["upi", "UPI"], ["cash", "Cash"], ["bank_transfer", "Bank transfer"], ["card", "Card"], ["other", "Other"]] as const;
const input = "min-h-12 w-full rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-[16px] text-[var(--haip-fg)]";
const lbl = "flex flex-col gap-1.5 text-[14px] font-semibold text-[var(--haip-fg)]";
const todayIso = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

export function RecordPaymentDrawer({ bookingId, guest, balance, open, onOpenChange, onDone }: {
  bookingId: string; guest: string; balance: number | null; open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void;
}) {
  const { toast } = useToast();
  const [f, setF] = useState({ amount: balance ? String(Math.round(balance)) : "", method: "upi", reference: "", paid_on: todayIso() });
  const save = useMutation({
    mutationFn: () => api.post(`/bookings/${bookingId}/payments`, {
      kind: "payment", amount: Number(f.amount), method: f.method, reference: f.reference || null, paid_on: f.paid_on,
    }),
    onSuccess: () => { toast({ title: `Payment recorded for ${guest}`, variant: "success" }); onOpenChange(false); onDone(); },
  });
  const ok = Number(f.amount) > 0 && !!f.paid_on;
  return (
    <Drawer open={open} onOpenChange={onOpenChange} title="Record payment" description={`${guest}${balance ? ` · balance ₹${Math.round(balance).toLocaleString("en-IN")}` : ""}`}
      footer={<button type="button" className="haip-btn-primary min-h-12 w-full" disabled={!ok || save.isPending} onClick={() => save.mutate()}>
        {save.isPending ? "Saving…" : "Record payment"}</button>}>
      <div className="flex flex-col gap-4">
        <label className={lbl}>Amount received (₹)
          <input className={input} inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value.replace(/[^\d.]/g, "") })} />
        </label>
        <div role="radiogroup" aria-label="How it was paid" className="flex flex-wrap gap-2">
          {METHODS.map(([v, l]) => (
            <button key={v} type="button" role="radio" aria-checked={f.method === v} onClick={() => setF({ ...f, method: v })}
              className={`min-h-11 rounded-full border px-4 text-[14px] ${f.method === v ? "border-primary bg-primary font-semibold text-primary-foreground" : "border-[var(--haip-border)]"}`}>{l}</button>
          ))}
        </div>
        <label className={lbl}>Reference (UTR or receipt number, optional)
          <input className={input} value={f.reference} maxLength={120} onChange={e => setF({ ...f, reference: e.target.value })} />
        </label>
        <label className={lbl}>Paid on<input type="date" className={input} value={f.paid_on} onChange={e => setF({ ...f, paid_on: e.target.value })} /></label>
        {save.isError && <p role="alert" className="text-[14px] text-[var(--haip-status-danger-fg)]">{errorMessage(save.error, "Couldn't record the payment. Try again.")}</p>}
      </div>
    </Drawer>
  );
}

/** Make a Razorpay link for the balance and send it on WhatsApp; when WhatsApp can't carry it, offer Copy. */
export function usePayLink(onDone: () => void) {
  const { toast } = useToast();
  return useMutation({
    mutationFn: (bookingId: string) => api.post(`/bookings/${bookingId}/payment-links`, { send_whatsapp: true }).then(r => r.data),
    onSuccess: (d: { short_url?: string; whatsapp?: { status?: string; reason?: string | null } }) => {
      if (d?.whatsapp?.status === "queued" || d?.whatsapp?.status === "sent") toast({ title: "Payment link sent on WhatsApp", variant: "success" });
      else {
        if (d?.short_url) navigator.clipboard?.writeText(d.short_url).catch(() => undefined);
        toast({ title: "Link made and copied", description: d?.whatsapp?.reason ?? "Paste it to the guest.", variant: "success" });
      }
      onDone();
    },
    onError: e => toast({ title: "Couldn't make the link", description: errorMessage(e, "Check Razorpay in Settings and try again."), variant: "error" }),
  });
}
