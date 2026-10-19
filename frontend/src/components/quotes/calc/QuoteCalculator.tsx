"use client";
// The rate calculator (docs: quote-simple mock-up). ONE component used two ways: inline on /dashboard/quotes, and inside the
// "Send quote" sheet opened from anywhere (QuoteSheetProvider), prefilled from the lead / chat / call / number it was opened on.
// The server prices every change (POST /quote-calculator/price, debounced) and returns the exact WhatsApp text; Copy, Send and
// Save re-price on the server and save the quote to the lead (POST /quote-calculator/quotes).
import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "@/lib/icons";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, EmptyState } from "@/components/ui/kit";
import { apiProblems } from "../ui";
import { AddonsCard, TaxCard } from "./AddonsCard";
import { QuotePanel } from "./QuotePanel";
import { SendTo } from "./SendTo";
import { TripCard } from "./TripCard";
import { useDebounced } from "./useDebounced";
import { actionGate, applyTrip, copyText, defaultForm, fromLine, toPayload, withoutPayLine } from "./calcHelpers";
import type { CalcContext, CalcForm, CalcSetup, LeadRow, PriceResult, QuoteOpenArgs, Receipt } from "./types";

/** React Query keys the opening list / card / thread read: refreshed after a quote is saved. */
export const REFRESH_KEYS = ["leads", "lead", "lead-detail", "work-queue", "conversation", "conversations", "calls"];

function hasTarget(a?: QuoteOpenArgs): boolean {
  return !!(a && (a.inquiryId || a.guestId || a.conversationId || a.callId || a.phone));
}

export function QuoteCalculator({ args, onHeader }: {
  args?: QuoteOpenArgs;
  /** The sheet shows "Quote for <name>" and the "Opened from ..." line in its own header. */
  onHeader?: (h: { title: string; from: string }) => void;
}) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const setup = useQuery<CalcSetup>({ queryKey: ["quote-calc-setup"], queryFn: () => api.get("/quote-calculator/setup").then(r => r.data), retry: 1, staleTime: 60_000 });
  const wantsCtx = hasTarget(args);
  const ctx = useQuery<CalcContext>({
    queryKey: ["quote-calc-context", args?.inquiryId, args?.guestId, args?.conversationId, args?.callId, args?.phone],
    queryFn: () => api.get("/quote-calculator/context", { params: {
      inquiry_id: args?.inquiryId || undefined, guest_id: args?.guestId || undefined, conversation_id: args?.conversationId || undefined,
      call_id: args?.callId || undefined, phone: args?.phone || undefined,
    } }).then(r => r.data),
    enabled: wantsCtx, retry: 0, staleTime: 0,
  });

  const [form, setForm] = useState<CalcForm | null>(null);
  const [lead, setLead] = useState<LeadRow | null>(null);
  const [receipt, setReceipt] = useState<{ r: Receipt; lead: LeadRow | null } | null>(null);
  const [copied, setCopied] = useState<boolean | null>(null);
  const [acting, setActing] = useState<"send" | "copy" | "save" | null>(null);
  const ctxReady = !wantsCtx || ctx.isSuccess || ctx.isError;

  useEffect(() => {
    if (form || !setup.data || !ctxReady) return;
    setForm(applyTrip(defaultForm(setup.data), ctx.data?.trip, setup.data));
    setLead(ctx.data?.lead ?? null);
  }, [form, setup.data, ctxReady, ctx.data]);

  const set = (patch: Partial<CalcForm>) => {
    setReceipt(null);
    setForm(f => {
      if (!f) return f;
      const next = { ...f, ...patch };
      if (patch.inclusive !== undefined && patch.inclusive !== f.inclusive && f.overrideOn) next.overridePrice = "";   // re-suggest in the new basis
      return next;
    });
  };

  const payload = useMemo(() => (form ? toPayload(form, lead?.inquiry_id ?? null) : null), [form, lead]);
  const debounced = useDebounced(payload, 250);
  const price = useQuery<PriceResult>({
    queryKey: ["quote-calc-price", debounced],
    queryFn: () => api.post("/quote-calculator/price", debounced).then(r => r.data),
    enabled: !!debounced, placeholderData: keepPreviousData, retry: 1, staleTime: 30_000,
  });
  const result = payload ? price.data : undefined;
  const pricing = price.isFetching || JSON.stringify(payload) !== JSON.stringify(debounced);

  // "Change the price" starts from the suggested price, in the basis of the inclusive switch.
  useEffect(() => {
    if (form?.overrideOn && !form.overridePrice && result?.ok && !result.override && result.net) {
      setForm(f => (f ? { ...f, overridePrice: String(Math.round(Number(result.net))) } : f));
    }
  }, [form?.overrideOn, form?.overridePrice, result]);

  const name = lead?.guest_name || ctx.data?.guest_name || args?.name || null;
  const from = fromLine(args?.from, ctx.data, args?.name);
  useEffect(() => { onHeader?.({ title: name ? `Quote for ${name}` : "New quote", from }); }, [name, from, onHeader]);

  const save = useMutation({
    mutationFn: (action: "send" | "copy" | "save") => {
      const target = lead!.kind === "new_trip" ? { guest_id: lead!.guest_id, inquiry_id: null } : { inquiry_id: lead!.inquiry_id };
      return api.post("/quote-calculator/quotes", { ...payload, ...target, action }).then(r => r.data as Receipt);
    },
  });

  const act = async (action: "send" | "copy" | "save") => {
    if (!form || !payload || !result?.ok) return;
    setCopied(null);
    if (!lead) {
      if (action === "copy") {
        const ok = await copyText(withoutPayLine(result.message_text ?? ""));
        toast({ variant: ok ? "success" : "error", title: ok ? "Copied. Pick a lead to save this quote." : "Couldn't copy. Select the message and copy it." });
      }
      return;
    }
    const before = lead;
    setActing(action);
    const run = save.mutateAsync(action);
    const copying = action === "copy"
      ? copyText(run.then(r => (r.how === "pending_approval" ? Promise.reject(new Error("waiting")) : r.message_text)))
      : Promise.resolve(null);
    try {
      const r = await run;
      const didCopy = await copying;
      setCopied(action === "copy" && r.how === "copied" ? didCopy : null);
      setReceipt({ r, lead: before });
      setLead({ ...before, kind: "lead", open: true, inquiry_id: r.lead.inquiry_id, stage_label: r.stage.to,
        stage_category: r.stage.moved ? "valid" : before.stage_category, created: false });
      REFRESH_KEYS.forEach(k => qc.invalidateQueries({ queryKey: [k] }));
      const title = r.how === "pending_approval" ? "Sent to the owner for OK" : r.how === "sent" ? "Quote sent on WhatsApp"
        : r.how === "copied" ? "Quote copied and saved" : action === "send" ? "Saved, not sent" : "Saved to the lead";
      toast({ variant: r.message?.status === "not_sent" ? "error" : "success", title, description: r.message?.status === "not_sent" ? r.message.message : undefined });
    } catch (e) {
      await copying.catch(() => null);
      const p = apiProblems(e);
      toast({ variant: "error", title: "Couldn't save the quote", description: p.message });
    } finally {
      setActing(null);
    }
  };

  if (setup.isPending || (wantsCtx && ctx.isPending) || (!form && !setup.isError)) {
    return (
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-3">{[1, 2, 3].map(i => <Skeleton key={i} className="h-36 rounded-2xl" />)}</div>
        <Skeleton className="h-96 rounded-2xl" />
      </div>
    );
  }
  if (setup.isError || !setup.data || !form) {
    const status = (setup.error as { response?: { status?: number } } | null)?.response?.status;
    return status === 403 ? (
      <Card><EmptyState title="Quotes are not open to your role" hint="Ask the owner to give your role the quotes permission in Roles & permissions." /></Card>
    ) : (
      <div role="alert" className="flex items-start gap-3 rounded-xl border border-[var(--haip-status-danger-border)] bg-[var(--haip-status-danger-bg)] px-4 py-3 text-sm text-[var(--haip-status-danger-fg)]">
        <AlertCircle size={16} className="mt-0.5 shrink-0" />
        <span className="flex-1">Couldn&apos;t load the rate card.</span>
        <button type="button" onClick={() => setup.refetch()} className="min-h-11 rounded-lg border border-current px-3 text-xs font-semibold sm:min-h-9">Try again</button>
      </div>
    );
  }

  const s = setup.data;
  const gate = actionGate({ result, lead, busy: pricing || !!acting });
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
      <div className="grid min-w-0 gap-4">
        {ctx.isError && (
          <p role="alert" className="rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-[13px] text-[var(--haip-status-warning-fg)]">
            Couldn&apos;t load that lead. Pick the lead under Send to.
          </p>
        )}
        <TripCard form={form} set={set} setup={s} result={result} />
        <AddonsCard form={form} set={set} />
        <TaxCard form={form} set={set} setup={s} />
      </div>
      <div className="min-w-0 lg:sticky lg:top-4">
        <QuotePanel form={form} set={set} result={result} pricing={pricing} failed={price.isError} onRetry={() => price.refetch()}
          gate={gate} threshold={s.settings.approval_threshold_percent} validDays={s.settings.valid_days}
          sendTo={<SendTo lead={lead} onLead={l => { setLead(l); setReceipt(null); }} sources={s.lead_sources}
            initialText={!ctx.data?.lead && ctx.data?.add?.phone ? ctx.data.add.phone : ""} />}
          acting={acting} onAct={act} receipt={receipt?.r ?? null} lead={receipt?.lead ?? null} copied={copied}
          razorpay={s.send_setup.razorpay_connected} />
      </div>
    </div>
  );
}
