"use client";
// "Invoices and messages" on the booking page: the invoices and receipts issued for this booking (open the PDF,
// reissue for owner/manager) and the WhatsApp messages HAIP sent about it, with their delivery state.
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { errorMessage, fmtDate, type BookingDetail } from "@/lib/bookings";
import { deliveryPill, docTitle, type BookingMessages, type InvoiceList } from "@/lib/invoices";

const smallBtn = "inline-flex min-h-9 pointer-coarse:min-h-11 items-center rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-xs font-semibold text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] disabled:opacity-50";

export function InvoicesMessagesCard({ booking, watch }: { booking: BookingDetail; watch: boolean }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const id = booking.id;
  // While a payment link is open the page polls, so the invoice and confirmation appear when the guest pays.
  const poll = watch ? 20_000 : false;
  const docs = useQuery<InvoiceList>({
    queryKey: ["booking-invoices", id], queryFn: () => api.get(`/bookings/${id}/invoices`).then(r => r.data), refetchInterval: poll,
  });
  const msgs = useQuery<BookingMessages>({
    queryKey: ["booking-messages", id], queryFn: () => api.get(`/bookings/${id}/booking-messages`).then(r => r.data), refetchInterval: poll,
  });

  const reissue = useMutation({
    mutationFn: () => api.post<InvoiceList>(`/bookings/${id}/invoices/reissue`, {}),
    onSuccess: res => {
      queryClient.setQueryData(["booking-invoices", id], res.data);
      toast({ variant: "success", title: "New invoice issued. Its PDF is ready in a minute." });
    },
    onError: e => toast({ variant: "error", title: errorMessage(e, "Could not issue the invoice") }),
  });

  async function openPdf(invoiceId: string) {
    // Open the tab first (inside the tap) so phone browsers do not block it, then point it at the signed link.
    const tab = window.open("", "_blank");
    try {
      const { data } = await api.get<{ url: string }>(`/invoices/${invoiceId}/pdf`);
      if (tab) tab.location.href = data.url; else window.location.assign(data.url);
    } catch (e) {
      tab?.close();
      toast({ variant: "error", title: errorMessage(e, "Could not open the PDF") });
    }
  }

  const list = docs.data?.invoices ?? [];
  const canReissue = !!docs.data?.can_reissue && booking.status !== "cancelled";
  const notApproved = msgs.data ? Object.values(msgs.data.templates).some(s => s !== "approved") : false;

  return (
    <Card>
      <CardHeader
        title="Invoices and messages"
        actions={canReissue && (
          <button type="button" className={smallBtn} disabled={reissue.isPending}
            onClick={() => {
              const msg = list.some(d => d.kind === "invoice" && d.status === "issued")
                ? "Issue a new invoice with today's amounts? The current one keeps its number and is marked replaced."
                : "Issue the invoice for this booking now?";
              if (confirm(msg)) reissue.mutate();
            }}>
            {reissue.isPending ? "Issuing..." : list.some(d => d.kind === "invoice") ? "Reissue invoice" : "Issue invoice"}
          </button>
        )}
      />
      <CardBody className="space-y-4 text-sm">
        {docs.isLoading ? <Skeleton className="h-14 rounded-xl" /> : docs.isError ? (
          <p role="alert" className="text-[var(--haip-status-danger-fg)]">
            Couldn&apos;t load the invoices. <button type="button" className="font-semibold underline" onClick={() => docs.refetch()}>Try again</button>
          </p>
        ) : list.length === 0 ? (
          <p className="text-[var(--haip-fg-subtle)]">No invoice yet. It is made, and sent with the booking confirmation, when the first payment arrives.</p>
        ) : (
          <ul className="divide-y divide-[var(--haip-border)]">
            {list.map(d => (
              <li key={d.id} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-[var(--haip-fg)]">{docTitle(d)}</p>
                  <p className="text-xs text-[var(--haip-fg-subtle)]">
                    {d.kind === "receipt" ? `${formatINR(d.total)} received` : `${formatINR(d.total)}${d.gst_rate > 0 ? " incl. GST" : ""}`}
                    {d.issued_at ? ` · ${fmtDate(d.issued_at)}` : ""}
                  </p>
                </div>
                {d.status !== "issued" && <StatusPill tone="neutral">{d.status === "superseded" ? "Replaced" : "Void"}</StatusPill>}
                <button type="button" className={smallBtn} disabled={!d.pdf_ready} onClick={() => openPdf(d.id)}>
                  {d.pdf_ready ? "View PDF" : "Preparing"}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div>
          <p className="mb-1 text-xs font-semibold text-[var(--haip-fg-subtle)]">WhatsApp messages</p>
          {msgs.isLoading ? <Skeleton className="h-10 rounded-xl" /> : msgs.isError ? (
            <p role="alert" className="text-[var(--haip-status-danger-fg)]">
              Couldn&apos;t load the messages. <button type="button" className="font-semibold underline" onClick={() => msgs.refetch()}>Try again</button>
            </p>
          ) : (msgs.data?.messages.length ?? 0) === 0 ? (
            <p className="text-[var(--haip-fg-subtle)]">None sent for this booking yet.</p>
          ) : (
            <ul className="divide-y divide-[var(--haip-border)]">
              {msgs.data!.messages.map(m => {
                const pill = deliveryPill(m.status);
                return (
                  <li key={m.id} className="flex items-center gap-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium text-[var(--haip-fg)]">{m.label ?? m.template ?? "Message"}</p>
                      <p className="truncate text-xs text-[var(--haip-fg-subtle)]">
                        {m.at ? new Date(m.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : ""}
                        {m.error ? ` · ${m.error}` : ""}
                      </p>
                    </div>
                    <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                  </li>
                );
              })}
            </ul>
          )}
          {notApproved && (
            <p className="mt-2 text-xs text-[var(--haip-fg-subtle)]">
              Some booking messages are not approved by Meta yet, so HAIP does not send them.{" "}
              {docs.data?.can_reissue
                ? <Link href="/dashboard/settings/invoices" className="font-medium text-primary hover:underline">See which</Link>
                : "An owner or manager can set them up."}
            </p>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
