"use client";
// Settings > AI: the two owner switches behind the AI sales agent (GET/PUT /ai/sales-agent). Managers can read them; only the
// owner can change them (the server enforces it and audits every change). Both default to today's behaviour: no prices in chat,
// sales agent off.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import { Loader2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, StatusPill } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { BTN_PRIMARY } from "@/components/quotes/ui";

type PriceMode = "handoff" | "grounded";
type AgentMode = "off" | "suggest" | "autopilot";
export type SalesAgentSettings = {
  price_disclosure: PriceMode;
  sales_agent_mode: AgentMode;
  readiness: { published_packages: number; auto_bookable: string[]; razorpay_connected: boolean; quote_template_status: string | null };
  checklist: ReadinessChecklist;
};

/** sales_agent_readiness.checklist: every step from "guest asks" to "booking paid". */
export type ReadinessRow = {
  key: string; group: "suggest" | "autopilot" | "after"; ok: boolean; label: string; detail: string;
  fix: { href: string; label: string } | null;
};
export type ReadinessChecklist = { mode: AgentMode; suggest_ready: boolean; autopilot_ready: boolean; rows: ReadinessRow[] };

const GROUPS: { id: ReadinessRow["group"]; title: string }[] = [
  { id: "suggest", title: "To prepare quotes a person sends (Suggest)" },
  { id: "autopilot", title: "Also needed for the AI to send them itself (Autopilot)" },
  { id: "after", title: "After the guest pays" },
];

export function ReadinessList({ checklist }: { checklist: ReadinessChecklist }) {
  return (
    <div className="space-y-4">
      {GROUPS.map(g => {
        const rows = checklist.rows.filter(r => r.group === g.id);
        if (!rows.length) return null;
        const ready = g.id === "suggest" ? checklist.suggest_ready : g.id === "autopilot" ? checklist.autopilot_ready : null;
        return (
          <section key={g.id} className="space-y-1.5">
            <h4 className="flex flex-wrap items-center gap-2 text-[13px] font-semibold text-[var(--haip-fg)]">
              {g.title}
              {ready !== null && <StatusPill tone={ready ? "success" : "neutral"}>{ready ? "Ready" : "Not ready"}</StatusPill>}
            </h4>
            <ul className="divide-y divide-[var(--haip-border)] rounded-xl border border-[var(--haip-border)]">
              {rows.map(r => (
                <li key={r.key} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-3 py-2">
                  <StatusPill tone={r.ok ? "success" : "warning"}>{r.ok ? "Done" : "To do"}</StatusPill>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13.5px] font-semibold text-[var(--haip-fg)]">{r.label}</span>
                    <span className="block break-words text-[12.5px] text-[var(--haip-fg-subtle)]">{r.detail}</span>
                  </span>
                  {r.fix && (
                    <a href={r.fix.href} className="inline-flex min-h-11 items-center text-[13px] font-semibold text-primary underline sm:min-h-0">
                      {r.fix.label}
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

const PRICE: { id: PriceMode; label: string; desc: string }[] = [
  { id: "handoff", label: "Team shares prices", desc: "The AI never states a price. It collects the details and a person shares the price. (Default)" },
  { id: "grounded", label: "AI quotes published prices", desc: "The AI may state a price only when it is the exact figure your published plans give for the guest's dates, party and route: GST, the advance, what is included and what is billed at actuals. Anything else goes to a person." },
];
const AGENT: { id: AgentMode; label: string; desc: string }[] = [
  { id: "off", label: "Off", desc: "The AI answers messages as it does today. (Default)" },
  { id: "suggest", label: "Suggest", desc: "The AI checks the booking calendar for the guest's dates and, with published prices on, prepares the quote. A person approves before the quote and payment link are sent." },
  { id: "autopilot", label: "Autopilot", desc: "As Suggest, but the AI sends the quote and payment link itself when every check passes: dates free right now, published prices, the route marked auto-bookable, Razorpay and the quote template ready. Otherwise it waits for a person. The booking, invoice and confirmation follow the payment, as with your team's quotes." },
];

function Choice<T extends string>({ name, value, options, onChange, disabled }: {
  name: string; value: T; options: { id: T; label: string; desc: string }[]; onChange: (v: T) => void; disabled: boolean;
}) {
  return (
    <div role="radiogroup" className="space-y-2">
      {options.map(o => (
        <label key={o.id} className={cn("flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border-2 p-3",
          value === o.id ? "border-primary bg-[var(--haip-primary-tint)]" : "border-[var(--haip-border)]", disabled && "cursor-default opacity-80")}>
          <input type="radio" name={name} checked={value === o.id} disabled={disabled} onChange={() => onChange(o.id)} className="mt-1 accent-primary" />
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-[var(--haip-fg)]">{o.label}</span>
            <span className="block text-[13px] text-[var(--haip-fg-subtle)]">{o.desc}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

export function SalesAgentSettingsCard() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { data: session } = useSession();
  const isOwner = (session?.user as { role?: string } | undefined)?.role === "owner";
  const { data, isPending, isError } = useQuery<SalesAgentSettings>({
    queryKey: ["ai-sales-agent"],
    queryFn: () => api.get("/ai/sales-agent").then(r => r.data),
    retry: (n, e) => (e as { response?: { status?: number } })?.response?.status !== 403 && n < 1,
  });
  const [price, setPrice] = useState<PriceMode>("handoff");
  const [agent, setAgent] = useState<AgentMode>("off");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (data) { setPrice(data.price_disclosure); setAgent(data.sales_agent_mode); setConfirmed(false); }
  }, [data]);
  const save = useMutation({
    mutationFn: () => api.put("/ai/sales-agent", { price_disclosure: price, sales_agent_mode: agent }).then(r => r.data),
    onSuccess: () => { toast({ variant: "success", title: "Sales agent settings saved" }); qc.invalidateQueries({ queryKey: ["ai-sales-agent"] }); },
    onError: () => toast({ variant: "error", title: "Couldn't save", description: "Only the owner can change these settings." }),
  });

  if (isPending) {
    return <Card><CardBody className="flex items-center gap-2 text-sm text-[var(--haip-fg-subtle)]"><Loader2 size={14} className="animate-spin" /> Loading sales agent settings…</CardBody></Card>;
  }
  if (isError || !data) {
    return <Card><CardBody className="text-sm text-[var(--haip-fg-subtle)]">Sales agent settings are visible to the owner and managers.</CardBody></Card>;
  }
  const changed = price !== data.price_disclosure || agent !== data.sales_agent_mode;
  const needsConfirm = agent === "autopilot" && data.sales_agent_mode !== "autopilot";

  return (
    <Card>
      <CardHeader title="AI sales agent" description={isOwner ? "Only you can change these. Every change is recorded." : "Only the owner can change these."} />
      <CardBody className="space-y-5">
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-[var(--haip-fg)]">Prices in chat</h3>
          <Choice name="price_disclosure" value={price} options={PRICE} onChange={setPrice} disabled={!isOwner} />
        </section>
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-[var(--haip-fg)]">Close the sale</h3>
          <Choice name="sales_agent_mode" value={agent} options={AGENT} onChange={v => { setAgent(v); setConfirmed(false); }} disabled={!isOwner} />
          {agent !== "off" && price === "handoff" && (
            <p className="text-[13px] text-[var(--haip-fg-2)]">With "Team shares prices" the AI checks the calendar but never prepares a quote.</p>
          )}
        </section>
        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-[var(--haip-fg)]">What the sales agent needs</h3>
          <ReadinessList checklist={data.checklist} />
        </section>
        {isOwner && needsConfirm && (
          <label className="flex min-h-11 items-start gap-3 text-[13px] text-[var(--haip-fg)]">
            <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} className="mt-1 accent-primary" />
            I understand the AI will send quotes and payment links to guests without a person checking each one.
          </label>
        )}
        {isOwner && (
          <button type="button" className={BTN_PRIMARY} disabled={!changed || save.isPending || (needsConfirm && !confirmed)} onClick={() => save.mutate()}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save"}
          </button>
        )}
      </CardBody>
    </Card>
  );
}
