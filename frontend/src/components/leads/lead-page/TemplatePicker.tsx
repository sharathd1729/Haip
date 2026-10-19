"use client";
// Outside WhatsApp's 24-hour window only an approved template can go. Same endpoints as the Inbox's template modal
// (GET /messaging/templates, POST /conversations/{id}/send-template), laid out inline for the lead composer.
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Loader2, Send } from "@/lib/icons";

interface Template { id: string; name: string; language: string; status: string; components: { type: string; text?: string }[] }

const body = (t?: Template | null) => t?.components.find(c => c.type === "BODY")?.text ?? "";
const slots = (text: string) => new Set(text.match(/\{\{\d+\}\}/g) ?? []).size;

export function TemplatePicker({ conversationId, name, onSent, onError }: {
  conversationId: string; name: string; onSent: () => void; onError: (msg: string) => void;
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const [vars, setVars] = useState<string[]>([]);
  const { data: templates = [], isPending, isError } = useQuery<Template[]>({
    queryKey: ["wa-templates"],
    queryFn: () => api.get("/messaging/templates").then(r => r.data),
    staleTime: 30_000,
  });
  const approved = templates.filter(t => t.status === "approved");
  const chosen = approved.find(t => t.id === picked) ?? null;
  const preview = vars.reduce((txt, v, i) => txt.replace(`{{${i + 1}}}`, v || `{{${i + 1}}}`), body(chosen));
  const send = useMutation({
    mutationFn: () => api.post(`/conversations/${conversationId}/send-template`, { template_id: picked, variables: vars }),
    onSuccess: () => { setPicked(null); setVars([]); onSent(); },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      onError(typeof d === "string" ? d : "The template was not sent. Please try again.");
    },
  });

  if (isPending) return <p className="text-[13px] text-[var(--haip-fg-subtle)]">Loading approved templates…</p>;
  if (isError) return <p className="text-[13px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t load the templates. Check your connection and try again.</p>;
  if (approved.length === 0) return <p className="text-[13px] text-[var(--haip-fg-subtle)]">No approved WhatsApp templates yet. Create one in WhatsApp → Templates and submit it to Meta.</p>;

  return (
    <div className="grid gap-2" data-testid="template-picker">
      <div role="radiogroup" aria-label={`Approved template for ${name}`} className="grid max-h-48 gap-1.5 overflow-y-auto">
        {approved.map(t => (
          <button key={t.id} type="button" role="radio" aria-checked={picked === t.id}
            onClick={() => { setPicked(t.id); setVars(Array.from({ length: slots(body(t)) }, () => "")); }}
            className={cn("flex min-h-11 items-center justify-between gap-2 rounded-xl border bg-[var(--haip-card)] px-3 py-2 text-left text-[13.5px]",
              picked === t.id ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
            <span className="min-w-0">
              <span className="block font-semibold text-[var(--haip-fg)]">{t.name.replace(/_/g, " ")}</span>
              <span className="block truncate text-[12px] text-[var(--haip-fg-subtle)]">{body(t)}</span>
            </span>
            {picked === t.id && <Check size={15} className="shrink-0 text-primary" aria-hidden />}
          </button>
        ))}
      </div>
      {chosen && (
        <>
          {vars.map((v, i) => (
            <label key={i} className="grid gap-1 text-[12.5px] font-semibold text-[var(--haip-fg-2)]">
              Value {i + 1}
              <input value={v} onChange={e => setVars(p => p.map((x, j) => (j === i ? e.target.value : x)))}
                className="min-h-11 rounded-lg border border-[var(--haip-border-strong)] bg-[var(--haip-card)] px-3 text-[16px] font-normal text-[var(--haip-fg)]" />
            </label>
          ))}
          <p className="whitespace-pre-wrap rounded-xl bg-[var(--haip-status-success-bg)] px-3 py-2 text-[14px] text-[var(--haip-fg)]">{preview}</p>
          <button type="button" onClick={() => send.mutate()} disabled={send.isPending || vars.some(v => !v.trim())}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 justify-self-end rounded-full bg-primary px-4 text-[13.5px] font-semibold text-primary-foreground disabled:opacity-60">
            {send.isPending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Send size={14} aria-hidden />} Send template
          </button>
        </>
      )}
    </div>
  );
}
