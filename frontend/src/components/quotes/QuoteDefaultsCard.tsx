"use client";
// Settings > Quotes > Defaults (owner / manager): the GST slab and "prices include GST" every new quote starts with, the
// advance %, how long a quote is valid, and how far below the suggested price an agent may go before the owner must OK it.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { cn } from "@/lib/utils";
import { BTN, BTN_PRIMARY, Field, INPUT, apiProblems } from "./ui";
import { cleanNumber } from "./calc/calcHelpers";
import type { CalcSetup } from "./calc/types";

type Settings = CalcSetup["settings"];

export function QuoteDefaultsCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<Settings>({ queryKey: ["quote-calc-settings"], queryFn: () => api.get("/quote-calculator/settings").then(r => r.data), retry: 0 });
  const [f, setF] = useState<Settings | null>(null);
  useEffect(() => { if (q.data) setF(q.data); }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put("/quote-calculator/settings", { ...f, valid_days: Number(f!.valid_days) || 3 }).then(r => r.data as Settings),
    onSuccess: d => { setF(d); qc.invalidateQueries({ queryKey: ["quote-calc-setup"] }); toast({ variant: "success", title: "Quote defaults saved", description: "New quotes start with these." }); },
    onError: e => toast({ variant: "error", title: "Couldn't save", description: apiProblems(e).message }),
  });

  if (q.isPending) return <Skeleton className="h-64 rounded-2xl" />;
  if (q.isError || !f) {
    return <Card><CardBody><p role="alert" className="text-[13px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t load the quote defaults.{" "}
      <button type="button" className={BTN} onClick={() => q.refetch()}>Try again</button></p></CardBody></Card>;
  }
  const num = (k: keyof Settings) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: cleanNumber(e.target.value) });
  return (
    <Card>
      <CardHeader title="Quote defaults" description="Every new quote starts with these. Agents can change the GST slab and the inclusive switch on a quote." />
      <CardBody className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="GST (%)" htmlFor="qd-gst" hint="0, 5, 18 or 40, or another rate"><input id="qd-gst" className={cn(INPUT, "num")} inputMode="decimal" value={f.gst_percent} onChange={num("gst_percent")} /></Field>
          <Field label="Advance to confirm (%)" htmlFor="qd-adv"><input id="qd-adv" className={cn(INPUT, "num")} inputMode="decimal" value={f.advance_percent} onChange={num("advance_percent")} /></Field>
          <Field label="Quote valid for (days)" htmlFor="qd-days"><input id="qd-days" className={cn(INPUT, "num")} inputMode="numeric" value={String(f.valid_days)} onChange={e => setF({ ...f, valid_days: Number(e.target.value.replace(/\D/g, "")) || 0 })} /></Field>
          <Field label="Owner OK below suggested by more than (%)" htmlFor="qd-th"><input id="qd-th" className={cn(INPUT, "num")} inputMode="decimal" value={f.approval_threshold_percent} onChange={num("approval_threshold_percent")} /></Field>
          <Field label="Largest discount without an OK (%)" htmlFor="qd-disc"><input id="qd-disc" className={cn(INPUT, "num")} inputMode="decimal" value={f.max_discount_percent} onChange={num("max_discount_percent")} /></Field>
          <Field label="Greeting" htmlFor="qd-greet" hint="The first word of the WhatsApp quote"><input id="qd-greet" className={INPUT} maxLength={40} value={f.greeting} onChange={e => setF({ ...f, greeting: e.target.value })} /></Field>
        </div>
        <label className="flex min-h-11 items-center gap-2.5 text-[14px] sm:min-h-10">
          <input type="checkbox" checked={f.prices_include_gst} onChange={e => setF({ ...f, prices_include_gst: e.target.checked })} className="size-5 accent-[var(--primary)]" />
          Prices include GST
        </label>
        <button type="button" className={BTN_PRIMARY} disabled={save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save defaults"}
        </button>
      </CardBody>
    </Card>
  );
}
