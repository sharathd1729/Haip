"use client";
// Lead page, "Send package": pick a PUBLISHED retail package (never a partner/b2b one), see the exact WhatsApp message, send.
// Backend: GET/POST /leads/{id}/package-share (package_share_service; conversations.send). Inside the guest's 24-hour window
// it goes as a normal message; outside it the approved template is used. When it cannot go (template waiting for Meta
// approval, personal-WhatsApp chat, no link), the sheet says why and offers Copy text instead. Prices only when the
// workspace shows prices (grounded); the server decides, the sheet just shows the preview.
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Check, Copy, Loader2, Send } from "@/lib/icons";
import { Drawer } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";

interface Pkg { key: string; name: string; summary: string; length: string; days: string[]; price: string | null; link: string | null; text: string }
interface Options { packages: Pkg[]; window_open: boolean; template_approved: boolean; personal_bridge_only: boolean; has_phone: boolean; price_shown: boolean }

function detail(e: unknown): { code?: string; message?: string; text?: string } {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return d && typeof d === "object" ? d as { code?: string; message?: string; text?: string } : { message: typeof d === "string" ? d : undefined };
}

export function blockedReason(o: Options | undefined, pkg: Pkg | undefined): string | null {
  if (!o || !pkg) return null;
  if (!o.has_phone) return "This guest has no phone number yet.";
  if (o.window_open) return null;
  if (o.personal_bridge_only) return "This chat is on a staff member's personal WhatsApp. Copy the text and send it from that phone.";
  if (!o.template_approved) return "Template waiting for Meta approval. The guest's 24-hour window is closed, so copy the text and send it from WhatsApp.";
  if (!pkg.link) return "The 24-hour window is closed and this package has no page to link to. Copy the text instead.";
  return null;
}

export function SendPackageSheet({ open, onClose, inquiryId, name }: { open: boolean; onClose: () => void; inquiryId: string; name: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [key, setKey] = useState<string | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  useEffect(() => { if (!open) { setKey(null); setRefused(null); } }, [open]);
  const q = useQuery<Options>({ queryKey: ["package-share", inquiryId], queryFn: () => api.get(`/leads/${inquiryId}/package-share`).then(r => r.data), enabled: open, staleTime: 30_000 });
  const pkg = q.data?.packages.find(p => p.key === key);
  const blocked = blockedReason(q.data, pkg) ?? refused;

  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); toast({ variant: "success", title: "Copied", description: "Paste it into the guest's WhatsApp chat." }); }
    catch { toast({ variant: "error", title: "Couldn't copy", description: "Select the text and copy it by hand." }); }
  };
  const send = useMutation({
    mutationFn: () => api.post(`/leads/${inquiryId}/package-share`, { package_key: key }).then(r => r.data as { status: string; how: string }),
    onSuccess: d => {
      toast({ variant: "success", title: d.status === "duplicate" ? "Already sent today" : "Package sent", description: d.how === "template" ? "Sent with the WhatsApp template." : "Sent on WhatsApp." });
      qc.invalidateQueries({ queryKey: ["lead-feed", inquiryId] });
      onClose();
    },
    onError: e => { const d = detail(e); setRefused(d.message ?? "Not sent. Copy the text instead."); },
  });

  return (
    <Drawer open={open} onOpenChange={o => { if (!o) onClose(); }} title="Send package" description={`A published package for ${name}, on WhatsApp.`}>
      {q.isPending ? (
        <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" aria-hidden /> Loading packages…</p>
      ) : q.isError || !q.data ? (
        <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load packages. <button type="button" className="font-semibold text-primary" onClick={() => q.refetch()}>Try again</button></p>
      ) : q.data.packages.length === 0 ? (
        <p className="text-sm text-[var(--haip-fg-muted)]">No published packages yet. Publish one in Settings → Packages and routes.</p>
      ) : (
        <div className="grid gap-3">
          <div className="grid gap-1.5" role="radiogroup" aria-label="Package">
            {q.data.packages.map(p => (
              <button key={p.key} type="button" role="radio" aria-checked={key === p.key} onClick={() => { setKey(p.key); setRefused(null); }}
                className={cn("flex min-h-11 items-center justify-between gap-2 rounded-xl border bg-[var(--haip-card)] px-3 py-2 text-left text-[14.5px] text-[var(--haip-fg)]",
                  key === p.key ? "border-primary ring-1 ring-primary" : "border-[var(--haip-border)]")}>
                <span><span className="block font-semibold">{p.name}</span><span className="block text-[12.5px] text-[var(--haip-fg-subtle)]">{p.length}{p.price ? ` · ${p.price}` : ""}</span></span>
                {key === p.key && <Check size={16} className="shrink-0 text-primary" aria-hidden />}
              </button>
            ))}
          </div>
          {pkg && (
            <>
              <pre className="whitespace-pre-wrap break-words rounded-xl border border-[var(--haip-border)] bg-[var(--haip-surface)] px-3 py-2 font-[inherit] text-[13.5px] text-[var(--haip-fg)]" aria-label="Message preview">{pkg.text}</pre>
              {blocked && <p className="rounded-xl border border-[var(--haip-status-warning-border)] bg-[var(--haip-status-warning-bg)] px-3 py-2 text-[13.5px] text-[var(--haip-status-warning-fg)]">{blocked}</p>}
              <div className="flex flex-wrap gap-2">
                {!blocked && (
                  <button type="button" disabled={send.isPending} onClick={() => send.mutate()}
                    className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl bg-primary px-4 text-[14px] font-semibold text-primary-foreground disabled:opacity-60">
                    {send.isPending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Send size={14} aria-hidden />} Send on WhatsApp
                  </button>
                )}
                <button type="button" onClick={() => copy(pkg.text)}
                  className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-[var(--haip-border-strong)] px-4 text-[14px] font-semibold text-[var(--haip-fg-2)]">
                  <Copy size={14} aria-hidden /> Copy text
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Drawer>
  );
}
