"use client";
// Settings > AI: "Ask a manager" (GET/PUT /ai/consult-settings). When the AI meets a question it must not answer alone, it holds
// its draft, tells the guest the team is checking, and asks a person. The owner sets business hours, how long each level has to
// answer, and the holding texts. Managers can read; only the owner saves (the server enforces it and audits every change).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { BTN_PRIMARY, INPUT, LABEL } from "@/components/quotes/ui";

export type ConsultSettings = {
  enabled: boolean; business_start: string; business_end: string; sla_minutes: number; offhours_reply_minutes: number;
  send_holding_reply: boolean; holding_text: string; holding_text_offhours: string; timezone: string;
  preview: { in_hours: string; off_hours: string };
};
type Editable = Omit<ConsultSettings, "timezone" | "preview">;
const FIELDS: (keyof Editable)[] = ["enabled", "business_start", "business_end", "sla_minutes", "offhours_reply_minutes",
  "send_holding_reply", "holding_text", "holding_text_offhours"];

export function AgentConsultSettingsCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const isOwner = (session?.user as { role?: string } | undefined)?.role === "owner";
  const { data, isPending, isError } = useQuery<ConsultSettings>({
    queryKey: ["ai-consult-settings"],
    queryFn: () => api.get("/ai/consult-settings").then(r => r.data),
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1,
  });
  const [form, setForm] = useState<Editable | null>(null);
  useEffect(() => { if (data) setForm(Object.fromEntries(FIELDS.map(k => [k, data[k]])) as Editable); }, [data]);
  const save = useMutation({
    mutationFn: (body: Partial<Editable>) => api.put("/ai/consult-settings", body).then(r => r.data),
    onSuccess: () => { toast({ variant: "success", title: "Ask-a-manager settings saved" }); qc.invalidateQueries({ queryKey: ["ai-consult-settings"] }); },
    onError: () => toast({ variant: "error", title: "Couldn't save", description: "Check the times (HH:MM) and texts. Only the owner can change these." }),
  });

  if (isPending || (data && !form)) {
    return <Card><CardBody className="flex items-center gap-2 text-sm text-[var(--haip-fg-subtle)]"><Loader2 size={14} className="animate-spin" /> Loading…</CardBody></Card>;
  }
  if (isError || !data || !form) {
    return <Card><CardBody className="text-sm text-[var(--haip-fg-subtle)]">Ask-a-manager settings are visible to the owner and managers.</CardBody></Card>;
  }
  const changes = Object.fromEntries(FIELDS.filter(k => form[k] !== data[k]).map(k => [k, form[k]])) as Partial<Editable>;
  const set = <K extends keyof Editable>(k: K, v: Editable[K]) => setForm({ ...form, [k]: v });
  const off = !isOwner;

  return (
    <Card>
      <CardHeader title="Ask a manager" description={`When the AI must not answer alone it holds its reply, tells the guest the team is checking, and asks you. Times in ${data.timezone}.`} />
      <CardBody className="space-y-4">
        <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg)]">
          <input type="checkbox" checked={form.enabled} disabled={off} onChange={e => set("enabled", e.target.checked)} className="accent-primary" />
          Ask a person before answering refunds, discounts, custom routes, partner rates, unpublished prices and guests who want a person
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><label className={LABEL} htmlFor="cs-start">Team starts</label>
            <input id="cs-start" type="time" className={INPUT} value={form.business_start} disabled={off} onChange={e => set("business_start", e.target.value)} /></div>
          <div><label className={LABEL} htmlFor="cs-end">Team stops</label>
            <input id="cs-end" type="time" className={INPUT} value={form.business_end} disabled={off} onChange={e => set("business_end", e.target.value)} /></div>
          <div><label className={LABEL} htmlFor="cs-sla">Minutes to answer (each level)</label>
            <input id="cs-sla" type="number" min={5} max={240} className={INPUT} value={form.sla_minutes} disabled={off} onChange={e => set("sla_minutes", Number(e.target.value))} /></div>
          <div><label className={LABEL} htmlFor="cs-off">Outside hours: answer this many minutes after opening</label>
            <input id="cs-off" type="number" min={0} max={240} className={INPUT} value={form.offhours_reply_minutes} disabled={off} onChange={e => set("offhours_reply_minutes", Number(e.target.value))} /></div>
        </div>
        <label className="flex min-h-11 items-center gap-2 text-sm text-[var(--haip-fg)]">
          <input type="checkbox" checked={form.send_holding_reply} disabled={off} onChange={e => set("send_holding_reply", e.target.checked)} className="accent-primary" />
          Tell the guest we're checking (once, never twice in a row)
        </label>
        <div><label className={LABEL} htmlFor="cs-text">Holding reply, business hours ({"{minutes}"})</label>
          <textarea id="cs-text" className={cn(INPUT, "h-20 py-2")} maxLength={400} value={form.holding_text} disabled={off} onChange={e => set("holding_text", e.target.value)} /></div>
        <div><label className={LABEL} htmlFor="cs-text-off">Holding reply, outside hours ({"{time}"}, {"{day}"})</label>
          <textarea id="cs-text-off" className={cn(INPUT, "h-20 py-2")} maxLength={400} value={form.holding_text_offhours} disabled={off} onChange={e => set("holding_text_offhours", e.target.value)} /></div>
        <div className="space-y-1 rounded-lg bg-[var(--haip-surface)] p-3 text-[13px] text-[var(--haip-fg-2)]">
          <p><span className="font-semibold">Guests see now:</span> {data.preview.in_hours}</p>
          <p><span className="font-semibold">After hours:</span> {data.preview.off_hours}</p>
        </div>
        {isOwner && (
          <button type="button" className={BTN_PRIMARY} disabled={!Object.keys(changes).length || save.isPending} onClick={() => save.mutate(changes)}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save"}
          </button>
        )}
      </CardBody>
    </Card>
  );
}
