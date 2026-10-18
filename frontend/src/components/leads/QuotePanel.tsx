"use client";

/* Package quote on a lead (backend endpoints/lead_quotes.py).
   Prices come only from published business records; staff may add custom lines. Issuing stores a snapshot and returns the
   WhatsApp text. Nothing here sends: the agent copies the text and sends it from the lead's official WhatsApp chat. */

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Copy, ExternalLink, FileText, Loader2, Plus, Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { formatINR } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, Drawer, StatusPill } from "@/components/ui/kit";

interface QuoteLine { label: string; amount: string; detail?: string; custom?: boolean }
interface Snapshot {
  package_name?: string; lines: QuoteLine[]; subtotal: string; gst?: string | null; gst_percent?: string | null; total: string;
  advance?: string | null; valid_until?: string | null; warnings?: string[];
}
interface IssuedQuote {
  id: string; status: string; is_active: boolean; amount: string; check_in: string | null; check_out: string | null;
  guests: number | null; created_at: string; snapshot: Snapshot | null; message_text?: string;
  validity?: { valid: boolean; reasons: string[] };
}
interface PackageOption { key: string; name: string; max_guests: number; min_nights: number; max_nights: number | null }
interface CustomLineDraft { label: string; amount: string }

const INPUT =
  "w-full min-h-11 rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:min-h-9 sm:text-[13px] " +
  "text-[var(--haip-fg)] placeholder:text-[var(--haip-text-subtle)] focus:outline-none focus:ring-2 focus:ring-primary/30";
const PRIMARY = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50 sm:min-h-9";
const SECONDARY = "inline-flex min-h-11 items-center justify-center gap-1.5 rounded-lg border border-[var(--haip-border)] px-3 text-sm font-semibold hover:bg-[var(--haip-surface)] disabled:opacity-50 sm:min-h-9";

const rupees = (v: string | null | undefined) => (v == null ? "—" : formatINR(Number(v)));

function errorText(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  if (Array.isArray(detail)) return "Check the dates, guests and custom lines.";
  return "Something went wrong. Try again.";
}

function Lines({ snap }: { snap: Snapshot }) {
  return (
    <div className="space-y-1 text-[13px]">
      {snap.lines.map((l, i) => (
        <div key={i} className="flex items-start justify-between gap-3">
          <span className="min-w-0 text-[var(--haip-fg-2)]">
            {l.label}{l.custom && <StatusPill tone="highlight" className="ml-1.5">Custom</StatusPill>}
          </span>
          <span className="shrink-0 tabular-nums text-[var(--haip-fg)]">{rupees(l.amount)}</span>
        </div>
      ))}
      {snap.gst != null && (
        <div className="flex justify-between text-[var(--haip-fg-subtle)]"><span>GST ({Number(snap.gst_percent)}%)</span><span className="tabular-nums">{rupees(snap.gst)}</span></div>
      )}
      <div className="flex justify-between border-t border-[var(--haip-border)] pt-1 font-semibold text-[var(--haip-fg)]">
        <span>Total</span><span className="tabular-nums">{rupees(snap.total)}</span>
      </div>
      {snap.advance != null && (
        <div className="flex justify-between text-[var(--haip-fg-subtle)]"><span>Advance</span><span className="tabular-nums">{rupees(snap.advance)}</span></div>
      )}
      {(snap.warnings ?? []).map(w => <p key={w} className="text-[12px] text-[var(--haip-status-warning-fg)]">{w}</p>)}
    </div>
  );
}

export function QuotePanel({ inquiryId, canWrite }: { inquiryId: string; canWrite: boolean }) {
  const { toast } = useToast();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ package_key: "", check_in: "", check_out: "", adults: "2", children: "0" });
  const [custom, setCustom] = useState<CustomLineDraft[]>([]);
  const [issued, setIssued] = useState<{ text: string; conversationId: string | null } | null>(null);

  const quotes = useQuery({
    queryKey: ["lead-quotes", inquiryId],
    queryFn: () => api.get(`/leads/${inquiryId}/quotes`).then(r => r.data as { quotes: IssuedQuote[]; conversation_id: string | null }),
  });
  const packages = useQuery({
    queryKey: ["lead-quote-packages", inquiryId],
    queryFn: () => api.get(`/leads/${inquiryId}/quotes/packages`).then(r => r.data as { ok: boolean; data: PackageOption[]; flags: string[] }),
    enabled: open,
  });

  const body = () => ({
    package_key: form.package_key, check_in: form.check_in, check_out: form.check_out,
    adults: Number(form.adults) || 1, children: Number(form.children) || 0,
    custom_lines: custom.filter(c => c.label.trim() && Number(c.amount) > 0).map(c => ({ label: c.label.trim(), amount: c.amount })),
  });
  const ready = form.package_key && form.check_in && form.check_out;

  const preview = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/quotes/preview`, body()).then(r => r.data as { ok: boolean; quote?: Snapshot; message?: string }),
  });
  const issue = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/quotes`, body()).then(r => r.data as { message_text: string; conversation_id: string | null }),
    onSuccess: (d) => {
      setIssued({ text: d.message_text, conversationId: d.conversation_id });
      qc.invalidateQueries({ queryKey: ["lead-quotes", inquiryId] });
      qc.invalidateQueries({ queryKey: ["lead", inquiryId] });
      toast({ title: "Quote issued", description: "Copy the message and send it from the chat.", variant: "success" });
    },
    onError: (e) => toast({ title: "Quote not issued", description: errorText(e), variant: "error" }),
  });

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast({ title: "Copied", description: "Paste it in the WhatsApp chat and send." });
    } catch {
      toast({ title: "Couldn't copy", description: "Select the text and copy it by hand.", variant: "error" });
    }
  }

  function close(next: boolean) {
    setOpen(next);
    if (!next) { setIssued(null); preview.reset(); }
  }

  const active = quotes.data?.quotes.find(q => q.is_active && q.status === "issued");
  const chatId = issued?.conversationId ?? quotes.data?.conversation_id ?? null;
  const pkgs = packages.data?.data ?? [];

  return (
    <Card>
      <CardHeader
        title="Package quote"
        description="Prices from published packages only. Nothing is sent until you send it."
        actions={canWrite ? <button type="button" onClick={() => setOpen(true)} className={SECONDARY}><FileText size={14} />New quote</button> : undefined}
      />
      <CardBody>
        {quotes.isLoading ? (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">Loading quotes…</p>
        ) : quotes.isError ? (
          <p className="flex items-center gap-1.5 text-[13px] text-[var(--haip-status-danger-fg)]">
            <AlertCircle size={14} />Couldn&apos;t load quotes.
            <button type="button" onClick={() => quotes.refetch()} className="underline">Try again</button>
          </p>
        ) : !active?.snapshot ? (
          <p className="text-[13px] text-[var(--haip-fg-subtle)]">No package quote issued yet.</p>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-[13px] text-[var(--haip-fg-2)]">
              <span className="font-semibold text-[var(--haip-fg)]">{active.snapshot.package_name}</span>
              <span>{active.check_in} → {active.check_out}</span>
              {active.validity && (active.validity.valid
                ? <StatusPill tone="success">Valid</StatusPill>
                : <StatusPill tone="warning">{active.validity.reasons[0] ?? "Re-quote"}</StatusPill>)}
            </div>
            <Lines snap={active.snapshot} />
            {active.message_text && (
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => copy(active.message_text!)} className={SECONDARY}><Copy size={14} />Copy message</button>
                {chatId && <Link href={`/dashboard/inbox?conversation=${chatId}`} className={SECONDARY}><ExternalLink size={14} />Open chat</Link>}
              </div>
            )}
          </div>
        )}
      </CardBody>

      <Drawer
        open={open}
        onOpenChange={close}
        title={issued ? "Quote issued" : "New package quote"}
        description={issued ? "Copy the message and send it from the WhatsApp chat." : "Pick a published package and the trip dates."}
        footer={issued ? (
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => copy(issued.text)} className={PRIMARY}><Copy size={14} />Copy message</button>
            {chatId
              ? <Link href={`/dashboard/inbox?conversation=${chatId}`} className={SECONDARY}><ExternalLink size={14} />Open chat</Link>
              : <span className="self-center text-[12px] text-[var(--haip-fg-subtle)]">No WhatsApp chat on the official number yet.</span>}
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={!ready || preview.isPending} onClick={() => preview.mutate()} className={SECONDARY}>
              {preview.isPending && <Loader2 size={14} className="animate-spin" />}Preview
            </button>
            <button type="button" disabled={!ready || !preview.data?.ok || issue.isPending} onClick={() => issue.mutate()} className={PRIMARY}>
              {issue.isPending && <Loader2 size={14} className="animate-spin" />}Issue quote
            </button>
          </div>
        )}
      >
        {issued ? (
          <pre className="whitespace-pre-wrap break-words rounded-lg bg-[var(--haip-surface)] p-3 text-[13px] text-[var(--haip-fg)]">{issued.text}</pre>
        ) : (
          <div className="space-y-4">
            <label className="block text-[13px] font-medium text-[var(--haip-fg-2)]">
              Package
              {packages.isLoading ? <p className="mt-1 text-[13px] text-[var(--haip-fg-subtle)]">Loading packages…</p>
                : packages.isError ? <p className="mt-1 text-[13px] text-[var(--haip-status-danger-fg)]">Couldn&apos;t load packages.</p>
                : pkgs.length === 0 ? <p className="mt-1 text-[13px] text-[var(--haip-fg-subtle)]">No published packages. Publish one under Settings → Knowledge → Structured Business Data.</p>
                : (
                  <select value={form.package_key} onChange={e => { setForm({ ...form, package_key: e.target.value }); preview.reset(); }} className={`${INPUT} mt-1`}>
                    <option value="">Choose a package</option>
                    {pkgs.map(p => <option key={p.key} value={p.key}>{p.name} (up to {p.max_guests} guests)</option>)}
                  </select>
                )}
            </label>
            <div className="grid grid-cols-2 gap-3">
              {(["check_in", "check_out"] as const).map(k => (
                <label key={k} className="block text-[13px] font-medium text-[var(--haip-fg-2)]">
                  {k === "check_in" ? "Check-in" : "Check-out"}
                  <input type="date" value={form[k]} onChange={e => { setForm({ ...form, [k]: e.target.value }); preview.reset(); }} className={`${INPUT} mt-1`} />
                </label>
              ))}
              {(["adults", "children"] as const).map(k => (
                <label key={k} className="block text-[13px] font-medium text-[var(--haip-fg-2)]">
                  {k === "adults" ? "Adults" : "Children"}
                  <input type="number" inputMode="numeric" min={k === "adults" ? 1 : 0} max={50} value={form[k]}
                    onChange={e => { setForm({ ...form, [k]: e.target.value }); preview.reset(); }} className={`${INPUT} mt-1`} />
                </label>
              ))}
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[13px] font-medium text-[var(--haip-fg-2)]">Custom lines</p>
                <button type="button" disabled={custom.length >= 10} onClick={() => setCustom([...custom, { label: "", amount: "" }])} className={SECONDARY}>
                  <Plus size={14} />Add line
                </button>
              </div>
              <p className="text-[12px] text-[var(--haip-fg-subtle)]">For anything the package doesn&apos;t list (a custom stop, decoration). Positive amounts only; discounts follow the published policy.</p>
              {custom.map((c, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input aria-label="Line label" placeholder="What it is" maxLength={80} value={c.label} className={INPUT}
                    onChange={e => { const n = [...custom]; n[i] = { ...c, label: e.target.value }; setCustom(n); preview.reset(); }} />
                  <input aria-label="Amount in rupees" placeholder="₹" type="number" inputMode="decimal" min={1} value={c.amount} className={`${INPUT} max-w-[7.5rem]`}
                    onChange={e => { const n = [...custom]; n[i] = { ...c, amount: e.target.value }; setCustom(n); preview.reset(); }} />
                  <button type="button" aria-label="Remove line" onClick={() => { setCustom(custom.filter((_, j) => j !== i)); preview.reset(); }}
                    className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:bg-[var(--haip-surface)] sm:min-h-9 sm:min-w-9">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>

            {preview.isError && <p className="text-[13px] text-[var(--haip-status-danger-fg)]">{errorText(preview.error)}</p>}
            {preview.data && !preview.data.ok && (
              <p className="flex items-start gap-1.5 text-[13px] text-[var(--haip-status-warning-fg)]"><AlertCircle size={14} className="mt-0.5 shrink-0" />{preview.data.message}</p>
            )}
            {preview.data?.ok && preview.data.quote && (
              <div className="rounded-lg border border-[var(--haip-border)] p-3"><Lines snap={preview.data.quote} /></div>
            )}
          </div>
        )}
      </Drawer>
    </Card>
  );
}
