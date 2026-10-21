"use client";
// Agency M3 outreach: WhatsApp campaign DRAFTS from approved promos (launched in WhatsApp > Campaigns, never here) and
// email newsletters from approved posts. Backend: endpoints/marketing_channels.py.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "next-auth/react";
import Link from "next/link";
import api from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { Card, CardBody, CardHeader, StatusPill, type Tone } from "@/components/ui/kit";
import { STUDIO, btn, btnPrimary, inputCls, studioError, when, type ContentItem } from "./types";

interface WaInfo {
  settings: { rates_inr: Record<string, number>; template_id: string | null; tags: string[] };
  templates: { id: string; name: string; category: string }[];
  campaigns: { id: string; name: string; status: string; created_at: string }[];
}
interface Estimate { recipients: number; rate_inr: number; total_inr: number; category: string; note: string }

const inr = (n: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(n);

function useWa() {
  return useQuery<WaInfo>({ queryKey: ["studio-whatsapp"], queryFn: () => api.get(`${STUDIO}/whatsapp`).then(r => r.data), staleTime: 60_000 });
}

/** In an approved promo: choose a template and an audience, see recipients and cost, create a DRAFT campaign. */
export function WhatsAppDraft({ item }: { item: ContentItem }) {
  const wa = useWa();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [template, setTemplate] = useState<string>("");
  const [tags, setTags] = useState("");
  const [est, setEst] = useState<Estimate | null>(null);
  const body = () => ({ template_id: template || wa.data?.settings.template_id || "", audience_filter: tags.trim() ? { tags: tags.split(/[\s,]+/).filter(Boolean) } : {},
    variable_map: { body: { "1": { source: "first_name" } } } });
  const estimate = useMutation({ mutationFn: () => api.post(`${STUDIO}/whatsapp/estimate`, body()).then(r => r.data as Estimate),
    onSuccess: setEst, onError: e => toast({ variant: "error", title: "No estimate", description: studioError(e, "Try again.") }) });
  const draft = useMutation({ mutationFn: () => api.post(`${STUDIO}/content/${item.id}/whatsapp`, body()),
    onSuccess: r => { qc.invalidateQueries({ queryKey: ["studio-whatsapp"] }); toast({ variant: "success", title: "Draft campaign made",
      description: `${r.data.recipients} people, about ${inr(r.data.total_inr)}. Launch it from WhatsApp › Campaigns.` }); },
    onError: e => toast({ variant: "error", title: "Not made", description: studioError(e, "Try again.") }) });
  if (item.kind !== "promo" || !["approved", "scheduled", "published"].includes(item.status) || !wa.data) return null;
  return (
    <section className="space-y-2 rounded-xl border border-[var(--haip-border)] p-3">
      <h3 className="text-[13px] font-bold">WhatsApp campaign</h3>
      {!wa.data.templates.length ? <p className="text-xs text-[var(--haip-fg-subtle)]">No approved WhatsApp template yet. Make one in WhatsApp › Templates.</p> : (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="space-y-1"><span className="text-xs font-semibold">Template</span>
              <select className={inputCls} value={template || wa.data.settings.template_id || ""} onChange={e => { setTemplate(e.target.value); setEst(null); }}>
                <option value="">Choose…</option>
                {wa.data.templates.map(t => <option key={t.id} value={t.id}>{t.name} ({t.category.toLowerCase()})</option>)}
              </select></label>
            <label className="space-y-1"><span className="text-xs font-semibold">Subscriber tags (blank = everyone opted in)</span>
              <input className={inputCls} value={tags} placeholder={wa.data.settings.tags.join(" ") || "past_guests"} onChange={e => { setTags(e.target.value); setEst(null); }} /></label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btn} disabled={!body().template_id || estimate.isPending} onClick={() => estimate.mutate()}>See recipients and cost</button>
            {est && <span className="text-sm">{est.recipients} people · about <span className="font-semibold">{inr(est.total_inr)}</span> ({inr(est.rate_inr)} each)</span>}
            {est && <button type="button" className={btnPrimary} disabled={draft.isPending || !est.recipients} onClick={() => draft.mutate()}>Make a draft campaign</button>}
          </div>
          <p className="text-xs text-[var(--haip-fg-subtle)]">Nothing is sent from here. An owner or manager launches the draft in <Link href="/dashboard/messaging/campaigns" className="text-primary underline">WhatsApp › Campaigns</Link>. The cost is an estimate from your per-message rates.</p>
        </>
      )}
    </section>
  );
}

interface Newsletter { id: string; subject: string; status: string; recipients: number; delivered: number; failed: number; created_by: string | null; sent_at: string | null; created_at: string }
const NL_TONE: Record<string, Tone> = { draft: "neutral", sending: "info", sent: "success", failed: "danger" };

/** Newsletters from approved posts. A person with approve rights sends, confirming consent each time. */
export function NewslettersPanel() {
  const { data: session } = useSession();
  const role = session?.user?.role;
  const canSend = role === "owner" || role === "manager";
  const qc = useQueryClient();
  const { toast } = useToast();
  const q = useQuery<{ newsletters: Newsletter[]; audience: number; email_ready: boolean }>({ queryKey: ["studio-newsletters"],
    queryFn: () => api.get(`${STUDIO}/newsletters`).then(r => r.data),
    refetchInterval: d => (d.state.data?.newsletters.some(n => n.status === "sending") ? 6000 : false) });
  const approved = useQuery<ContentItem[]>({ queryKey: ["studio-content", "approved-for-email"],
    queryFn: () => api.get(`${STUDIO}/content`, { params: { status: "approved" } }).then(r => r.data) });
  const [subject, setSubject] = useState("");
  const [intro, setIntro] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["studio-newsletters"] });
  const fail = (title: string) => (e: unknown) => toast({ variant: "error", title, description: studioError(e, "Try again.") });
  const create = useMutation({ mutationFn: () => api.post(`${STUDIO}/newsletters`, { subject, intro: intro || null, content_ids: picked }),
    onSuccess: () => { setSubject(""); setIntro(""); setPicked([]); refresh(); toast({ variant: "success", title: "Newsletter draft saved" }); }, onError: fail("Not saved") });
  const send = useMutation({ mutationFn: (id: string) => api.post(`${STUDIO}/newsletters/${id}/send`, { consent_confirmed: true }),
    onSuccess: r => { setConfirm(null); refresh(); toast({ variant: "success", title: `Sending to ${r.data.recipients} guests` }); }, onError: fail("Not sent") });
  const d = q.data;
  if (!d) return null;
  return (
    <Card>
      <CardHeader title="Email newsletter" description={`${d.audience} guest${d.audience === 1 ? " has" : "s have"} an email address and agreed to marketing.${d.email_ready ? "" : " Email sending is not set up on this server yet."}`} />
      <CardBody className="space-y-4">
        <form className="space-y-2" onSubmit={e => { e.preventDefault(); create.mutate(); }}>
          <label className="block space-y-1"><span className="text-xs font-semibold">Subject</span>
            <input className={inputCls} maxLength={200} value={subject} onChange={e => setSubject(e.target.value)} placeholder="Diwali in the hills: three open weekends" /></label>
          <label className="block space-y-1"><span className="text-xs font-semibold">Opening lines (optional)</span>
            <textarea className={inputCls} rows={2} maxLength={2000} value={intro} onChange={e => setIntro(e.target.value)} /></label>
          <p className="text-xs font-semibold">Approved posts to include (up to 4)</p>
          <div className="flex flex-wrap gap-1.5">
            {(approved.data ?? []).slice(0, 20).map(c => { const on = picked.includes(c.id); return (
              <button key={c.id} type="button" aria-pressed={on} onClick={() => setPicked(on ? picked.filter(x => x !== c.id) : picked.length < 4 ? [...picked, c.id] : picked)}
                className={`min-h-11 rounded-full border px-3 text-[13px] sm:min-h-9 ${on ? "border-primary bg-primary text-primary-foreground" : "border-[var(--haip-border)]"}`}>{c.title}</button>); })}
            {!approved.data?.length && <span className="text-xs text-[var(--haip-fg-subtle)]">Approve a post first.</span>}
          </div>
          <button type="submit" className={btn} disabled={subject.trim().length < 3 || !picked.length || create.isPending}>Save newsletter draft</button>
        </form>
        {d.newsletters.length > 0 && (
          <ul className="space-y-2 border-t border-[var(--haip-border)] pt-3">
            {d.newsletters.map(n => (
              <li key={n.id} className="flex flex-wrap items-center gap-2 text-sm">
                <StatusPill tone={NL_TONE[n.status] ?? "neutral"}>{n.status}</StatusPill>
                <span className="font-semibold">{n.subject}</span>
                <span className="text-xs text-[var(--haip-fg-subtle)]">{n.status === "draft" ? when(n.created_at) : `${n.delivered}/${n.recipients} sent${n.failed ? `, ${n.failed} failed` : ""}`}</span>
                <a className="text-xs font-semibold text-primary" href={`${STUDIO}/newsletters/${n.id}/preview`} onClick={async e => {
                  e.preventDefault(); const r = await api.get(`${STUDIO}/newsletters/${n.id}/preview`, { responseType: "text" });
                  const w = window.open("", "_blank"); if (w) { w.document.write(r.data as string); w.document.close(); } }}>Preview</a>
                {n.status === "draft" && canSend && (confirm === n.id ? (
                  <span className="flex flex-wrap items-center gap-2 text-xs">
                    These {d.audience} guests agreed to marketing email.
                    <button type="button" className={btnPrimary} disabled={send.isPending} onClick={() => send.mutate(n.id)}>Yes, send</button>
                    <button type="button" className={btn} onClick={() => setConfirm(null)}>Cancel</button>
                  </span>) : <button type="button" className={btn} disabled={!d.email_ready || !d.audience} onClick={() => setConfirm(n.id)}>Send…</button>)}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

/** Owner defaults: approved promos that target WhatsApp get a draft campaign with this template and audience. */
export function WhatsAppDefaults() {
  const wa = useWa();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [template, setTemplate] = useState<string | null>(null);
  const [tags, setTags] = useState<string | null>(null);
  const [rate, setRate] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.put(`${STUDIO}/whatsapp`, {
      template_id: template ?? wa.data?.settings.template_id ?? null,
      tags: (tags ?? wa.data?.settings.tags.join(" ") ?? "").split(/[\s,]+/).filter(Boolean),
      variable_map: { body: { "1": { source: "first_name" } } },
      ...(rate !== null ? { rates_inr: { MARKETING: Number(rate) } } : {}),
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["studio-whatsapp"] }); toast({ variant: "success", title: "WhatsApp defaults saved" }); },
    onError: e => toast({ variant: "error", title: "Not saved", description: studioError(e, "Try again.") }),
  });
  const s = wa.data?.settings;
  if (!wa.data || !s) return null;
  return (
    <form className="grid gap-2 sm:grid-cols-[1fr_1fr_8rem_auto] sm:items-end" onSubmit={e => { e.preventDefault(); save.mutate(); }}>
      <label className="space-y-1"><span className="text-xs font-semibold">Default template</span>
        <select className={inputCls} value={template ?? s.template_id ?? ""} onChange={e => setTemplate(e.target.value)}>
          <option value="">None: no automatic drafts</option>
          {wa.data.templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select></label>
      <label className="space-y-1"><span className="text-xs font-semibold">Subscriber tags</span>
        <input className={inputCls} value={tags ?? s.tags.join(" ")} onChange={e => setTags(e.target.value)} placeholder="past_guests" /></label>
      <label className="space-y-1"><span className="text-xs font-semibold">₹ per message</span>
        <input className={inputCls} inputMode="decimal" value={rate ?? String(s.rates_inr.MARKETING)} onChange={e => setRate(e.target.value)} /></label>
      <button type="submit" className={btn} disabled={save.isPending}>Save</button>
      <p className="text-xs text-[var(--haip-fg-subtle)] sm:col-span-4">Only opted-in subscribers are used for automatic drafts. Check the rate against your Meta invoice.</p>
    </form>
  );
}
