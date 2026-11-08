"use client";
// Guest add-ons on a booking's ops file (trip or stay): the private add-ons link (copy it, or send it on WhatsApp while the
// guest's 24-hour window is open), the guest's requests waiting for a person's OK (Approve = availability re-checked and the
// Razorpay link made and sent; Decline), and what the guest has paid. Backend: /ops/files/{id}/addons*,
// /ops/addon-orders/{id}/approve|decline (services/guest_addons.py).
import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { inr, type AddonOrder } from "@/lib/guestAddons";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Check your connection and try again.";
}

const STATUS: Record<AddonOrder["status"], { label: string; tone: "warning" | "info" | "success" | "neutral" }> = {
  awaiting_approval: { label: "Needs your OK", tone: "warning" },
  awaiting_payment: { label: "Link sent, not paid", tone: "info" },
  paid: { label: "Paid", tone: "success" },
  declined: { label: "Declined", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

const names = (o: AddonOrder) => o.items.map(i => (i.quantity > 1 ? `${i.name} ×${i.quantity}` : i.name)).join(", ");

export function AddonsCard({ fileId, canWrite, onChanged }: { fileId: string; canWrite: boolean; onChanged?: () => void }) {
  const { toast } = useToast();
  const [data, setData] = useState<{ orders: AddonOrder[]; open: boolean; offer_count: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setData((await api.get(`/ops/files/${fileId}/addons`)).data); setFailed(false); }
    catch { setFailed(true); }
  }, [fileId]);
  useEffect(() => { load(); }, [load]);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try { await fn(); } catch (e) { toast({ title: "That didn't work", description: errorText(e), variant: "error" }); }
    finally { setBusy(null); }
  };
  const copy = () => run("copy", async () => {
    const url = (await api.post(`/ops/files/${fileId}/addons/link`)).data.url as string;
    await navigator.clipboard.writeText(url);
    toast({ title: "Link copied", description: "Paste it to the guest on WhatsApp.", variant: "success" });
  });
  const send = () => run("send", async () => {
    await api.post(`/ops/files/${fileId}/addons/send`);
    toast({ title: "Sent on WhatsApp", variant: "success" });
  });
  const approve = (o: AddonOrder) => run(o.id, async () => {
    const r = (await api.post(`/ops/addon-orders/${o.id}/approve`)).data as { url: string; sent: boolean };
    if (!r.sent) await navigator.clipboard.writeText(r.url).catch(() => undefined);
    toast({ title: "Approved", description: r.sent ? "The payment link is on its way on WhatsApp."
      : "WhatsApp window closed: the payment link is copied, send it yourself.", variant: "success" });
    await load(); onChanged?.();
  });
  const decline = (o: AddonOrder) => run(o.id, async () => {
    await api.post(`/ops/addon-orders/${o.id}/decline`, { reason: null });
    toast({ title: "Declined", variant: "success" });
    await load(); onChanged?.();
  });

  const waiting = data?.orders.filter(o => o.status === "awaiting_approval").length ?? 0;
  return (
    <Card id="ops-addons">
      <CardHeader title="Guest add-ons" tone="plain"
        description={data ? `The guest picks and pays extras on a private link · ${data.offer_count} on offer` : "Extras the guest buys on a private link"}
        actions={waiting > 0 ? <StatusPill tone="warning">{waiting} to approve</StatusPill> : undefined} />
      <CardBody className="flex flex-col gap-2 px-4 pb-4">
        {!data && !failed && <p className="text-[14px] text-[var(--haip-fg-subtle)]">Loading…</p>}
        {failed && (
          <p className="text-[14px] text-[var(--haip-fg-muted)]">Couldn&apos;t load add-ons.{" "}
            <button type="button" className="font-semibold text-[var(--haip-primary)] underline" onClick={load}>Try again</button></p>
        )}
        {data && data.orders.length === 0 && <p className="text-[14px] text-[var(--haip-fg-muted)]">Nothing picked yet.</p>}
        {data?.orders.map(o => (
          <div key={o.id} className="flex flex-col gap-2 border-t border-[var(--haip-border)] pt-2 first:border-t-0 first:pt-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[15px]">{names(o)} <span className="text-[14px] text-[var(--haip-fg-muted)]">· {inr(o.amount)}</span></p>
              <StatusPill tone={STATUS[o.status].tone}>{STATUS[o.status].label}</StatusPill>
            </div>
            {canWrite && o.status === "awaiting_approval" && (
              <div className="flex gap-2">
                <button type="button" className="haip-btn-primary min-h-11 flex-1" disabled={!!busy} onClick={() => approve(o)}>
                  {busy === o.id ? "Working…" : "Approve and send link"}</button>
                <button type="button" className="haip-btn-secondary min-h-11 px-4" disabled={!!busy} onClick={() => decline(o)}>Decline</button>
              </div>
            )}
          </div>
        ))}
        {canWrite && data?.open && (
          <div className="mt-1 flex flex-wrap gap-2">
            <button type="button" className="haip-btn-secondary min-h-12 flex-1" disabled={!!busy} onClick={copy}>
              {busy === "copy" ? "Copying…" : "Copy add-ons link"}</button>
            <button type="button" className="haip-btn-secondary min-h-12 flex-1" disabled={!!busy} onClick={send}>
              {busy === "send" ? "Sending…" : "Send on WhatsApp"}</button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
