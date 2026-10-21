"use client";
// Lead page, "Where they came from" (agency M6): the first and last MEASURED touch (ad, post, website link, first
// contact) next to what the guest SAID when asked "How did you first hear about us?". The two are never merged.
// Backend: GET /leads/{id}/touches, PUT /leads/{id}/heard-about (leads.write, audited).
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2 } from "@/lib/icons";
import { Card, CardBody, CardHeader } from "@/components/ui/kit";
import { useToast } from "@/components/ui/toast";
import { istDate } from "./format";

interface Touch { at: string | null; kind: "ad" | "post" | "website" | "first_contact"; channel: string | null; content_title: string | null; ad_id: string | null; detail: string | null }
interface Touches { first: Touch | null; last: Touch | null; credited: Touch | null; heard_about: string | null; heard_about_note: string | null; choices: { value: string; label: string }[] }

const KIND: Record<Touch["kind"], string> = { ad: "Ad", post: "Instagram post", website: "Website link", first_contact: "First contact" };

function describe(t: Touch | null): string {
  if (!t) return "Not recorded";
  const what = t.content_title ? `“${t.content_title}”` : t.ad_id ? `Meta ad ${t.ad_id}` : t.detail || t.channel || "";
  return [KIND[t.kind], what].filter(Boolean).join(": ") + (t.at ? ` · ${istDate(t.at)}` : "");
}

export function WhereFromCard({ inquiryId, canEdit }: { inquiryId: string; canEdit: boolean }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const key = ["lead-touches", inquiryId];
  const q = useQuery<Touches>({ queryKey: key, queryFn: () => api.get(`/leads/${inquiryId}/touches`).then(r => r.data), staleTime: 60_000 });
  const [answer, setAnswer] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => { if (q.data) { setAnswer(q.data.heard_about ?? ""); setNote(q.data.heard_about_note ?? ""); } }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.put(`/leads/${inquiryId}/heard-about`, { heard_about: answer || null, note: note || null }).then(r => r.data),
    onSuccess: d => { qc.setQueryData(key, d); toast({ variant: "success", title: "Saved" }); },
    onError: () => toast({ variant: "error", title: "Not saved", description: "Try again." }),
  });
  const t = q.data && Array.isArray(q.data.choices) ? q.data : undefined;   // a malformed reply shows the error line
  const dirty = !!t && (answer !== (t.heard_about ?? "") || note !== (t.heard_about_note ?? ""));
  return (
    <Card>
      <CardHeader title="Where they came from" description="What HAIP measured, next to what the guest told you." />
      <CardBody className="grid gap-3">
        {q.isPending ? (
          <p className="flex items-center gap-2 text-sm text-[var(--haip-fg-muted)]"><Loader2 size={14} className="animate-spin" /> Loading…</p>
        ) : q.isError || !t ? (
          <p className="text-sm text-[var(--haip-fg-muted)]">Couldn&apos;t load this. Refresh to try again.</p>
        ) : (
          <>
            <dl className="grid gap-2 text-[14px]">
              <div className="grid gap-0.5"><dt className="text-[12px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">First touch</dt><dd className="text-[var(--haip-fg)] [overflow-wrap:anywhere]">{describe(t.first)}</dd></div>
              <div className="grid gap-0.5"><dt className="text-[12px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Last touch</dt><dd className="text-[var(--haip-fg)] [overflow-wrap:anywhere]">{describe(t.last)}</dd></div>
              {t.credited && t.credited !== t.last && (
                <div className="grid gap-0.5"><dt className="text-[12px] font-semibold uppercase tracking-wide text-[var(--haip-fg-subtle)]">Credited post or ad</dt><dd className="text-[var(--haip-fg)] [overflow-wrap:anywhere]">{describe(t.credited)}</dd></div>
              )}
            </dl>
            <label className="grid gap-1">
              <span className="text-[13px] font-semibold text-[var(--haip-fg-2)]">How did you first hear about us? (ask the guest)</span>
              <select className="min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:text-sm" disabled={!canEdit || save.isPending}
                value={answer} onChange={e => setAnswer(e.target.value)}>
                <option value="">Not asked yet</option>
                {t.choices.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </label>
            {answer && (
              <input className="min-h-11 w-full rounded-lg border border-[var(--haip-border)] bg-[var(--haip-card)] px-3 text-base sm:text-sm" maxLength={200} disabled={!canEdit}
                placeholder="Their words (optional), e.g. “saw the monsoon reel”" value={note} onChange={e => setNote(e.target.value)} />
            )}
            {canEdit && dirty && (
              <button type="button" disabled={save.isPending} onClick={() => save.mutate()}
                className="inline-flex min-h-11 items-center justify-center justify-self-start rounded-xl bg-primary px-3.5 text-[14px] font-semibold text-primary-foreground disabled:opacity-50">
                {save.isPending ? "Saving…" : "Save answer"}
              </button>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
