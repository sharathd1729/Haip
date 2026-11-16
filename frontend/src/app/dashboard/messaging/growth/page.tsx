"use client";
// WhatsApp growth tools (WhatsApp step 3): tracked click-to-chat links with a QR code and a website chat button, and
// the in-chat booking form. Backend: endpoints/wa_growth.py, services/wa_entry_links.py, services/wa_booking_form.py.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, ClipboardList, Copy, Download, Loader2, Plus, Trash2 } from "@/lib/icons";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardBody, CardHeader, EmptyState, PageHeader, StatusPill } from "@/components/ui/kit";
import { Skeleton } from "@/components/ui/skeleton";

interface EntryLink {
  id: string; name: string; prefill_text: string; phone: string; active: boolean;
  clicks: number; chats: number; last_clicked_at: string | null; created_at: string;
  url: string; wa_me: string; qr_svg_url: string; widget_snippet: string;
}
interface FormStatus { connected: boolean; flow_id: string | null; published: boolean; error: string | null }

const INPUT = "w-full px-3 py-2.5 border border-[var(--haip-border)] rounded-xl text-base sm:text-sm focus:outline-none focus:ring-2 focus:ring-primary/30";
const detail = (e: unknown, fallback: string) => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked: the text is visible to copy by hand */ } }}
      className="min-h-11 flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium border border-[var(--haip-border)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)] active:scale-[0.98] transition-transform">
      {done ? <Check size={13} /> : <Copy size={13} />} {done ? "Copied" : label}
    </button>
  );
}

function LinkRow({ link, onToggle, onDelete }: { link: EntryLink; onToggle: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const rate = link.clicks ? Math.round((link.chats / link.clicks) * 100) : null;
  return (
    <li className="py-3 border-t border-[var(--haip-border)] first:border-t-0">
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => setOpen(o => !o)} aria-expanded={open} className="min-w-0 flex-1 text-left min-h-11">
          <p className="text-sm font-semibold text-[var(--haip-fg)] truncate">{link.name}</p>
          <p className="text-[11.5px] text-[var(--haip-fg-subtle)] truncate">{link.prefill_text || "No first message"}</p>
        </button>
        <div className="flex items-center gap-4 text-right">
          <div><p className="text-base font-bold tabular-nums text-[var(--haip-fg)]">{link.clicks.toLocaleString()}</p><p className="text-[11px] text-[var(--haip-fg-subtle)]">taps</p></div>
          <div><p className="text-base font-bold tabular-nums text-[var(--haip-fg)]">{link.chats.toLocaleString()}</p><p className="text-[11px] text-[var(--haip-fg-subtle)]">chats{rate !== null ? ` · ${rate}%` : ""}</p></div>
          {!link.active && <StatusPill tone="neutral">Off</StatusPill>}
        </div>
      </div>
      {open && (
        <div className="mt-3 grid gap-4 sm:grid-cols-[140px_minmax(0,1fr)]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={link.qr_svg_url} alt={`QR code for ${link.name}`} className="h-[140px] w-[140px] rounded-xl border border-[var(--haip-border)] bg-white p-1" />
          <div className="space-y-3 min-w-0">
            <div>
              <p className="text-[11px] font-semibold text-[var(--haip-fg-2)] mb-1">Link (bio, ads, email)</p>
              <p className="text-xs font-mono text-[var(--haip-fg-muted)] break-all">{link.url}</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold text-[var(--haip-fg-2)] mb-1">Website chat button: paste before &lt;/body&gt;</p>
              <p className="text-xs font-mono text-[var(--haip-fg-muted)] break-all">{link.widget_snippet}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <CopyButton text={link.url} label="Copy link" />
              <CopyButton text={link.widget_snippet} label="Copy website code" />
              <a href={link.qr_svg_url} download={`${link.name.replace(/[^a-z0-9]+/gi, "-")}-qr.svg`}
                className="min-h-11 flex items-center gap-1.5 px-3 rounded-lg text-xs font-medium border border-[var(--haip-border)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
                <Download size={13} /> QR code
              </a>
              <button type="button" onClick={onToggle}
                className="min-h-11 px-3 rounded-lg text-xs font-medium border border-[var(--haip-border)] text-[var(--haip-fg-2)] hover:bg-[var(--haip-surface)]">
                {link.active ? "Switch off" : "Switch on"}
              </button>
              <button type="button" onClick={() => { if (confirm(`Delete "${link.name}"? Its QR code and website button stop working.`)) onDelete(); }}
                aria-label={`Delete ${link.name}`}
                className="min-h-11 w-11 flex items-center justify-center rounded-lg text-[var(--haip-fg-subtle)] hover:text-[var(--haip-status-danger-fg)] hover:bg-[var(--haip-status-danger-bg)]">
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

function NewLinkForm({ needsPhone, onDone }: { needsPhone: boolean; onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", prefill_text: "Hi! I'd like to know more about your stays.", phone: "" });
  const create = useMutation({
    mutationFn: () => api.post("/messaging/entry-links", { ...form, phone: form.phone || null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["wa-entry-links"] }); onDone(); },
  });
  return (
    <form onSubmit={e => { e.preventDefault(); create.mutate(); }} className="space-y-3 rounded-xl bg-[var(--haip-surface)] p-3">
      <div>
        <label htmlFor="link-name" className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1">Name</label>
        <input id="link-name" required maxLength={80} value={form.name} placeholder="Instagram bio" onChange={e => setForm(f => ({ ...f, name: e.target.value }))} className={INPUT} />
      </div>
      <div>
        <label htmlFor="link-text" className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1">First message the guest sends</label>
        <textarea id="link-text" rows={2} maxLength={400} value={form.prefill_text} onChange={e => setForm(f => ({ ...f, prefill_text: e.target.value }))} className={INPUT} />
        <p className="text-[11.5px] text-[var(--haip-fg-subtle)] mt-1">A short reference is added at the end so the chat is counted against this link.</p>
      </div>
      {needsPhone && (
        <div>
          <label htmlFor="link-phone" className="text-xs font-semibold text-[var(--haip-fg-2)] block mb-1">WhatsApp number</label>
          <input id="link-phone" inputMode="tel" required value={form.phone} placeholder="+919876543210" onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} className={INPUT} />
        </div>
      )}
      {create.isError && <p className="text-xs text-[var(--haip-status-danger-fg)] flex items-center gap-1.5"><AlertCircle size={13} /> {detail(create.error, "Couldn't create the link.")}</p>}
      <div className="flex gap-2">
        <button type="button" onClick={onDone} className="min-h-11 flex-1 rounded-xl border border-[var(--haip-border)] text-sm text-[var(--haip-fg-muted)]">Cancel</button>
        <button type="submit" disabled={create.isPending} className="min-h-11 flex-1 rounded-xl bg-primary text-white text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-50">
          {create.isPending && <Loader2 size={14} className="animate-spin" />} Create link
        </button>
      </div>
    </form>
  );
}

function BookingFormCard() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useQuery<FormStatus>({
    queryKey: ["wa-booking-form"], queryFn: () => api.get("/messaging/booking-form").then(r => r.data),
  });
  const publish = useMutation({
    mutationFn: () => api.post("/messaging/booking-form/publish").then(r => r.data),
    onSuccess: (d: FormStatus) => qc.setQueryData(["wa-booking-form"], d),
  });
  return (
    <Card>
      <CardHeader icon={ClipboardList} title="Booking form in WhatsApp"
        description="Guests pick dates and party size inside the chat. Answers land on the lead." />
      <CardBody className="space-y-3">
        {isLoading ? <Skeleton className="h-10 rounded-xl" /> : isError ? (
          <p className="text-xs text-[var(--haip-status-danger-fg)]">Couldn&apos;t load the form status.</p>
        ) : data?.published ? (
          <p className="text-sm text-[var(--haip-fg-2)] flex items-center gap-2"><StatusPill tone="success">Live</StatusPill> Send it from any WhatsApp chat in the Inbox.</p>
        ) : (
          <>
            <p className="text-sm text-[var(--haip-fg-muted)]">{data?.connected ? "Publish HAIP's booking form on your WhatsApp account once. Meta reviews nothing extra." : "Connect WhatsApp first under Settings > Integrations."}</p>
            {data?.error && <p className="text-xs text-[var(--haip-status-danger-fg)]">Last try: {data.error}</p>}
            <button type="button" disabled={!data?.connected || publish.isPending} onClick={() => publish.mutate()}
              className="min-h-11 px-4 rounded-xl bg-primary text-white text-sm font-semibold flex items-center gap-2 disabled:opacity-50">
              {publish.isPending && <Loader2 size={14} className="animate-spin" />} Publish booking form
            </button>
            {publish.isError && <p className="text-xs text-[var(--haip-status-danger-fg)]">{detail(publish.error, "Couldn't publish. Try again.")}</p>}
          </>
        )}
      </CardBody>
    </Card>
  );
}

export default function GrowthPage() {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const { data, isLoading, isError, refetch } = useQuery<{ links: EntryLink[]; workspace_phone: string }>({
    queryKey: ["wa-entry-links"], queryFn: () => api.get("/messaging/entry-links").then(r => r.data),
  });
  const patch = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => api.patch(`/messaging/entry-links/${id}`, { active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wa-entry-links"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/messaging/entry-links/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wa-entry-links"] }),
  });
  const links = data?.links ?? [];

  return (
    <div className="mx-auto max-w-4xl px-4 py-5 sm:px-6 space-y-5">
      <PageHeader title="Growth tools" subtitle="Links, QR codes and a website button that open a WhatsApp chat, with taps and chats counted." />
      <Card>
        <CardHeader title="Click-to-chat links" description="Every count is all-time for that link."
          actions={!adding && <button type="button" onClick={() => setAdding(true)} className="min-h-11 px-3 rounded-xl bg-primary text-white text-sm font-semibold flex items-center gap-1.5"><Plus size={14} /> New link</button>} />
        <CardBody className="space-y-3">
          {adding && <NewLinkForm needsPhone={!data?.workspace_phone} onDone={() => setAdding(false)} />}
          {isLoading ? (
            <div className="space-y-2">{[0, 1].map(i => <Skeleton key={i} className="h-14 rounded-xl" />)}</div>
          ) : isError ? (
            <div className="py-6 text-center">
              <p className="text-sm text-[var(--haip-fg-2)]">Couldn&apos;t load your links.</p>
              <button type="button" onClick={() => refetch()} className="mt-2 min-h-11 px-3 text-xs font-semibold text-primary">Try again</button>
            </div>
          ) : links.length === 0 && !adding ? (
            <EmptyState title="No links yet" hint="Make one for your Instagram bio, a flyer QR code or your website, and see which brings chats."
              action={<button type="button" onClick={() => setAdding(true)} className="min-h-11 px-4 rounded-xl bg-primary text-white text-sm font-semibold">Create your first link</button>} />
          ) : (
            <ul className={cn(adding && "pt-2")}>
              {links.map(l => (
                <LinkRow key={l.id} link={l} onToggle={() => patch.mutate({ id: l.id, active: !l.active })} onDelete={() => remove.mutate(l.id)} />
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
      <BookingFormCard />
    </div>
  );
}
