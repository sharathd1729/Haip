"use client";
// A saved calculator quote (/dashboard/quotes?quote=<id>, the link in the owner's approval task and push): the owner or a
// manager approves a lowered price here; once approved, the agent sends or copies it from here without pricing it again.
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, EmptyState, StatusPill } from "@/components/ui/kit";
import { BTN, BTN_PRIMARY, apiProblems } from "../ui";
import { ReceiptBox } from "./QuotePanel";
import { REFRESH_KEYS } from "./QuoteCalculator";
import { copyText, dayLabel, money } from "./calcHelpers";
import type { Receipt, SavedQuoteView } from "./types";

const STATUS: Record<string, { label: string; tone: "warning" | "success" | "neutral" | "danger" }> = {
  pending_approval: { label: "Waiting for the owner's OK", tone: "warning" }, issued: { label: "Ready to send", tone: "success" },
  accepted: { label: "Paid · booked", tone: "success" }, superseded: { label: "Replaced by a newer quote", tone: "neutral" },
  withdrawn: { label: "Withdrawn", tone: "neutral" },
};

export function SavedQuote({ quoteId }: { quoteId: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [copied, setCopied] = useState<boolean | null>(null);
  const q = useQuery<SavedQuoteView>({ queryKey: ["quote-calc-saved", quoteId], queryFn: () => api.get(`/quote-calculator/quotes/${quoteId}`).then(r => r.data), retry: 0 });
  const done = () => { qc.invalidateQueries({ queryKey: ["quote-calc-saved", quoteId] }); REFRESH_KEYS.forEach(k => qc.invalidateQueries({ queryKey: [k] })); };
  const approve = useMutation({
    mutationFn: () => api.post(`/quote-calculator/quotes/${quoteId}/approve`).then(r => r.data),
    onSuccess: () => { done(); toast({ variant: "success", title: "Approved", description: "The agent can send it now." }); },
    onError: e => toast({ variant: "error", title: "Couldn't approve", description: apiProblems(e).message }),
  });
  const share = useMutation({ mutationFn: (action: "send" | "copy") => api.post(`/quote-calculator/quotes/${quoteId}/share`, { action }).then(r => r.data as Receipt) });
  const act = async (action: "send" | "copy") => {
    const run = share.mutateAsync(action);
    const copying = action === "copy" ? copyText(run.then(r => r.message_text)) : Promise.resolve(null);
    try {
      const r = await run;
      setCopied(action === "copy" ? await copying : null);
      setReceipt(r);
      done();
    } catch (e) {
      await copying.catch(() => null);
      toast({ variant: "error", title: action === "send" ? "Couldn't send" : "Couldn't copy", description: apiProblems(e).message });
    }
  };

  if (q.isPending) return <Skeleton className="h-80 rounded-2xl" />;
  if (q.isError || !q.data) {
    const status = (q.error as { response?: { status?: number } } | null)?.response?.status;
    return <Card><EmptyState title={status === 404 ? "Quote not found" : "Couldn't load the quote"}
      hint={status === 404 ? "It may belong to a lead you can't see." : undefined}
      action={status === 404 ? undefined : <button type="button" className={BTN} onClick={() => q.refetch()}>Try again</button>} /></Card>;
  }
  const v = q.data;
  const snap = v.snapshot;
  const st = STATUS[v.status] ?? { label: v.status, tone: "neutral" as const };
  return (
    <Card className="mx-auto max-w-2xl">
      <CardBody className="space-y-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-[family-name:var(--font-display)] text-[17px] font-semibold">Quote {v.quote_number}{v.lead ? ` · ${v.lead.guest_name}` : ""}</h2>
          <StatusPill tone={st.tone}>{st.label}</StatusPill>
        </div>
        <p className="num text-[14px]">
          <strong>{money(snap.total)}</strong> · {String(snap.package_name ?? "Trip")} · valid till {dayLabel(snap.valid_until)}
          {v.created_by_name ? ` · by ${v.created_by_name}` : ""}{v.approved_by_name ? ` · approved by ${v.approved_by_name}` : ""}
        </p>
        {snap.override && (
          <p className="text-[13px] text-[var(--haip-fg-2)]">
            {Number(snap.override.below_percent) > 0 ? `${snap.override.below_percent}% below the suggested ${money(String(snap.suggested_total ?? ""))}` : "Price changed by the agent"}
            {snap.override.reason ? ` · Reason (team only): ${snap.override.reason}` : ""}
          </p>
        )}
        <div className="max-h-[380px] overflow-auto whitespace-pre-wrap rounded-[12px_12px_12px_4px] bg-[var(--haip-primary-tint)] px-3.5 py-3 text-[14px] leading-relaxed">{v.message_text}</div>
        <div className="flex flex-wrap gap-2">
          {v.can_approve && (
            <button type="button" className={BTN_PRIMARY} disabled={approve.isPending} onClick={() => approve.mutate()}>
              {approve.isPending ? <Loader2 size={14} className="animate-spin" /> : "Approve this price"}
            </button>
          )}
          {v.can_share && (
            <>
              <button type="button" className={BTN} disabled={share.isPending} onClick={() => act("copy")}>Copy quote</button>
              <button type="button" className={BTN_PRIMARY} disabled={share.isPending} onClick={() => act("send")}>
                {share.isPending ? <Loader2 size={14} className="animate-spin" /> : "Send on WhatsApp"}
              </button>
            </>
          )}
          {v.lead && <Link href={`/dashboard/leads/${v.lead.inquiry_id}`} className={BTN}>Open the lead</Link>}
        </div>
        {!v.can_share && v.blocked_reason && !v.can_approve && <p className="text-[13px] text-[var(--haip-fg-subtle)]">{v.blocked_reason}</p>}
        {receipt && <ReceiptBox receipt={receipt} lead={null} copied={copied} />}
      </CardBody>
    </Card>
  );
}
