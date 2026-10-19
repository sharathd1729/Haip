"use client";
// Collect money for a booking: a Razorpay link sent on WhatsApp (a normal message inside the guest's 24-hour window, else the
// approved payment-link template), or a payment already received (UPI, cash, bank transfer) recorded in the ledger.
import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { Copy } from "@/lib/icons";
import api from "@/lib/api";
import { formatINR, timeAgo } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { ActionSheet, SheetOption, sheetBtn, sheetInput, sheetLabel } from "@/components/bookings/ActionSheet";
import { METHOD_LABEL, errorMessage, fmtDate, type BookingDetail, type PayMethod, type PaymentLink } from "@/lib/bookings";
import { BALANCE_TEMPLATE, type BookingMessages } from "@/lib/invoices";
import { todayIST } from "@/lib/bookingAgenda";

const METHODS: PayMethod[] = ["upi", "cash", "bank_transfer", "card", "other"];

/** Put a fresh booking in the cache and make every list, count and figure that shows its money fetch again. */
export function refreshBooking(qc: QueryClient, b: BookingDetail) {
  qc.setQueryData(["booking", b.id], b);
  qc.invalidateQueries({ queryKey: ["bookings"] });
  qc.invalidateQueries({ queryKey: ["bookings-summary"] });
  qc.invalidateQueries({ queryKey: ["bookings-occupancy"] });
}

export function CollectSheet({ bookingId, open, onClose }: { bookingId: string; open: boolean; onClose: () => void }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const { data: b } = useQuery<BookingDetail>({
    queryKey: ["booking", bookingId], queryFn: () => api.get(`/bookings/${bookingId}`).then(r => r.data), enabled: open,
  });
  const { data: msgs } = useQuery<BookingMessages>({
    queryKey: ["booking-messages", bookingId], queryFn: () => api.get(`/bookings/${bookingId}/booking-messages`).then(r => r.data),
    enabled: open, staleTime: 60_000,
  });
  const { data: rzp } = useQuery<{ connected: boolean }>({
    queryKey: ["razorpay-status"], queryFn: () => api.get("/payments/razorpay").then(r => r.data), enabled: open, staleTime: 60_000, retry: false,
  });

  const due = b?.financials.outstanding ?? 0;
  const [mode, setMode] = useState<"link" | "record">("link");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<PayMethod>("upi");
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(todayIST());
  const [link, setLink] = useState<PaymentLink | null>(null);
  useEffect(() => { if (open) { setAmount(due > 0 ? String(due) : ""); setLink(null); setReference(""); setPaidOn(todayIST()); } }, [open, due]);
  // No Razorpay account: recording a payment is the only way.
  useEffect(() => { if (rzp?.connected === false) setMode("record"); }, [rzp?.connected]);

  const value = Number(amount);
  const valid = value > 0 && value <= due + 0.005;
  const first = (b?.guest?.name || "the guest").split(" ")[0];
  const wa = b?.whatsapp;
  const templateReady = msgs?.templates?.[BALANCE_TEMPLATE] === "approved";
  const canSend = !!wa?.window_open || templateReady;

  const record = useMutation({
    mutationFn: () => api.post<BookingDetail>(`/bookings/${bookingId}/payments`, {
      kind: "payment", amount: value, method, reference: reference.trim() || undefined, paid_on: paidOn,
    }),
    onSuccess: res => {
      refreshBooking(qc, res.data);
      const left = res.data.financials.outstanding;
      toast({ variant: "success", title: `${formatINR(value)} recorded · ${left > 0 ? `${formatINR(left)} still due` : "fully paid"}` });
      onClose();
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not record the payment") }),
  });

  const makeLink = useMutation({
    mutationFn: (send: boolean) => api.post<PaymentLink>(`/bookings/${bookingId}/payment-links`, { amount: value, send_whatsapp: send }),
    onSuccess: (res, send) => {
      qc.invalidateQueries({ queryKey: ["booking", bookingId] });
      qc.invalidateQueries({ queryKey: ["booking-messages", bookingId] });
      const sent = res.data.whatsapp;
      if (send && sent?.status === "queued") {
        toast({ variant: "success", title: `Link for ${formatINR(value)} sent on WhatsApp`, description: "Marked paid by itself once the guest pays." });
        onClose();
        return;
      }
      setLink(res.data);
      if (send) toast({ variant: "warning", title: `Link made, not sent: ${sent?.reason ?? "unknown reason"}. Copy it instead.` });
      else navigator.clipboard?.writeText(res.data.short_url).then(
        () => toast({ variant: "success", title: "Payment link copied" }),
        () => toast({ variant: "warning", title: "Link ready. Copy it from the box." }));
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not create the link") }),
  });

  return (
    <ActionSheet open={open} onClose={onClose} title={`Collect from ${first}`}>
      {!b ? <Skeleton className="h-40 rounded-xl" /> : due <= 0 ? (
        <p className="text-sm text-[var(--haip-fg-2)]">Nothing is due on this booking. It is paid in full.</p>
      ) : (
        <>
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">
            {b.property?.name ?? "No vehicle yet"} · {fmtDate(b.check_in, false)} to {fmtDate(b.check_out, false)} · <span className="tabular-nums">{formatINR(due)}</span> still due
            {b.next_due ? `, ${formatINR(b.next_due.amount)} ${b.next_due.overdue ? "overdue since" : "due"} ${fmtDate(b.next_due.due_date, false)}` : ""}
          </p>
          <label className={sheetLabel}>Amount (₹)
            <input className={`${sheetInput} tabular-nums`} inputMode="decimal" value={amount} aria-invalid={!!amount && !valid}
              onChange={e => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} />
            {!!amount && !valid && <span className="font-normal text-[var(--haip-status-danger-fg)]">Enter an amount up to {formatINR(due)}.</span>}
          </label>
          <div className="grid gap-2">
            <SheetOption on={mode === "link"} onClick={() => rzp?.connected !== false && setMode("link")} title="Razorpay link on WhatsApp"
              hint={rzp?.connected === false ? "Razorpay is not connected for this workspace."
                : wa?.window_open ? `Goes as a normal message (${first} wrote ${timeAgo(wa.last_inbound_at)}). Marked paid by itself once the guest pays.`
                  : templateReady ? `Goes with the approved payment-link template${wa?.last_inbound_at ? ` (last message ${timeAgo(wa.last_inbound_at)})` : ""}. Marked paid by itself once the guest pays.`
                    : `Can't go on WhatsApp now: ${first} hasn't written in the last 24 hours and the payment template is not approved. Make the link and copy it.`} />
            <SheetOption on={mode === "record"} onClick={() => setMode("record")} title="Record a payment already received" hint="UPI, cash or bank transfer" />
          </div>
          {rzp?.connected === false && mode === "record" && (
            <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">To collect online, <Link href="/dashboard/settings/payments" className="font-semibold text-primary hover:underline">connect Razorpay</Link>.</p>
          )}
          {mode === "record" ? (
            <>
              <div className="grid grid-cols-2 gap-2.5">
                <label className={sheetLabel}>How was it paid?
                  <select className={sheetInput} value={method} onChange={e => setMethod(e.target.value as PayMethod)}>
                    {METHODS.map(m => <option key={m} value={m}>{METHOD_LABEL[m]}</option>)}
                  </select>
                </label>
                <label className={sheetLabel}>Received on
                  <input type="date" className={sheetInput} max={todayIST()} value={paidOn} onChange={e => setPaidOn(e.target.value)} />
                </label>
              </div>
              <label className={sheetLabel}>Reference (optional)
                <input className={sheetInput} placeholder="UTR or receipt number" value={reference} onChange={e => setReference(e.target.value)} />
              </label>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={sheetBtn.primary} disabled={!valid || record.isPending} onClick={() => record.mutate()}>
                  {record.isPending ? "Recording…" : "Record payment"}
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={sheetBtn.primary} disabled={!valid || !canSend || makeLink.isPending} onClick={() => makeLink.mutate(true)}>
                  {makeLink.isPending ? "Working…" : "Send link"}
                </button>
                <button type="button" className={sheetBtn.secondary} disabled={!valid || makeLink.isPending} onClick={() => makeLink.mutate(false)}>
                  <Copy size={14} /> Copy link
                </button>
              </div>
              {link && (
                <div className="space-y-1.5 rounded-xl border border-[var(--haip-border)] bg-[var(--haip-card)] p-3">
                  <p className="text-[12.5px] font-semibold text-[var(--haip-fg-2)]">Payment link for {formatINR(link.amount)}</p>
                  <input readOnly value={link.short_url} onFocus={e => e.currentTarget.select()} aria-label="Payment link" className={`${sheetInput} font-mono text-[14px]`} />
                </div>
              )}
            </>
          )}
          <p className="text-[12.5px] text-[var(--haip-fg-subtle)]">Sent from the business WhatsApp number inside HAIP and logged on the booking. The security deposit is collected separately and is never part of this amount.</p>
        </>
      )}
    </ActionSheet>
  );
}
